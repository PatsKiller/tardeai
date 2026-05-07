import React, { useEffect, useState, useMemo } from 'react'
import { Bar } from 'react-chartjs-2'
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, Tooltip } from 'chart.js'

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip)

const GREEN = '#4ADE80'
const RED = '#F87171'
const AMBER = '#F59E0B'
const BLUE = '#60A5FA'
const GREY = '#475569'
const BORDER = '#1E293B'
const BG = '#0D1626'

const tooltipOpts = { backgroundColor: '#0F172A', titleColor: '#E2E8F0', bodyColor: '#94A3B8', borderColor: BORDER, borderWidth: 1 }

function StatCard({ label, value, sub, color = '#E2E8F0' }: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: '8px', padding: '16px' }}>
      <div style={{ fontSize: '9px', color: GREY, letterSpacing: '0.1em', fontWeight: 600, marginBottom: '6px' }}>{label}</div>
      <div style={{ fontSize: '20px', fontWeight: 700, color }}>{value}</div>
      {sub && <div style={{ fontSize: '11px', color: '#475569', marginTop: '4px' }}>{sub}</div>}
    </div>
  )
}

function MiniBar({ value, max, color = '#2E86D4', label = '', count = 0 }: { value: number; max: number; color?: string; label?: string; count?: number }) {
  const pct = max > 0 ? (value / max * 100) : 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '5px 0' }}>
      <span style={{ minWidth: '140px', fontSize: '12px', color: '#94A3B8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{label}</span>
      <div style={{ flex: 1, height: '6px', background: BORDER, borderRadius: '3px', overflow: 'hidden' }}>
        <div style={{ width: `${Math.min(Math.abs(pct), 100)}%`, height: '100%', background: color, borderRadius: '3px' }} />
      </div>
      <span style={{ fontSize: '11px', color: GREY, minWidth: '30px', textAlign: 'right' }}>{count}</span>
      <span style={{ fontSize: '11px', color, minWidth: '44px', textAlign: 'right', fontWeight: 600 }}>
        {value >= 0 ? '+' : ''}${Math.abs(value) >= 1000 ? (Math.abs(value) / 1000).toFixed(1) + 'K' : Math.abs(value).toFixed(0)}
      </span>
    </div>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: '11px', color: GREY, letterSpacing: '0.1em', fontWeight: 600, marginBottom: '14px' }}>{children}</div>
}

const fmt$ = (v: number | null | undefined) => {
  if (v == null) return '—'
  const abs = Math.abs(v)
  const sign = v >= 0 ? '+' : '-'
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}K`
  return `${sign}$${abs.toFixed(0)}`
}

export default function JournalAnalytics() {
  const [report, setReport] = useState<any>(null)
  const [unannotated, setUnannotated] = useState<any>(null)
  const [btAnalytics, setBtAnalytics] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      fetch('/api/v2/journal/report').then(r => r.json()),
      fetch('/api/v2/journal/unannotated').then(r => r.json()).catch(() => ({ ok: false })),
      fetch('/api/v2/journal/backtest-analytics').then(r => r.json()).catch(() => ({ ok: false }))
    ]).then(([r, u, bt]) => {
      if (r.ok) setReport(r.data)
      if (u.ok) setUnannotated(u.data)
      if (bt.ok) setBtAnalytics(bt.data)
    }).finally(() => setLoading(false))
  }, [])

  const coveragePct = unannotated ? unannotated.coverage_pct : (report?.annotation_coverage ? Math.round(report.annotation_coverage.reviewed / Math.max(report.annotation_coverage.total_trades, 1) * 100) : 0)
  const reviewedCount = unannotated?.annotated_count ?? report?.annotation_coverage?.reviewed ?? 0
  const totalCount = unannotated?.total ?? report?.annotation_coverage?.total_trades ?? 0

  if (loading) return <div style={{ padding: '40px', color: BLUE, fontSize: '14px' }}>Loading Journal Analytics...</div>

  const s = report?.summary
  if (!s) return <div style={{ padding: '40px', color: RED }}>Failed to load analytics data</div>

  const gradeColors: Record<string, string> = { A: GREEN, B: BLUE, C: AMBER, D: RED }

  // Build grade counts from backtest_grades
  const gradeCount = (type: 'entry_grade' | 'exit_grade') => {
    const counts: Record<string, number> = { A: 0, B: 0, C: 0, D: 0 }
    for (const g of (report?.backtest_grades || [])) {
      const grade = g[type]
      if (grade && counts[grade] !== undefined) counts[grade] += g.trades
    }
    return counts
  }
  const entryGrades = gradeCount('entry_grade')
  const exitGrades = gradeCount('exit_grade')

  return (
    <div style={{ padding: '24px', color: '#E2E8F0', maxWidth: '1400px', margin: '0 auto' }}>
      {/* Header */}
      <div style={{ marginBottom: '24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontSize: '24px', fontWeight: 700, color: '#F1F5F9', marginBottom: '4px' }}>Journal Analytics</h1>
          <p style={{ color: GREY, fontSize: '13px' }}>
            {s.total_trades} closed trades · {reviewedCount} annotated ({coveragePct}% coverage)
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <a href="/v2/journal-reports" style={{ background: '#1E3A5F', border: '1px solid #2E86D4', color: BLUE, padding: '9px 18px', borderRadius: '6px', fontSize: '12px', textDecoration: 'none', fontWeight: 600 }}>
            Full Reports
          </a>
          <a href="/v2/journal" style={{ background: '#0F172A', border: `1px solid ${BORDER}`, color: '#94A3B8', padding: '9px 18px', borderRadius: '6px', fontSize: '12px', textDecoration: 'none', fontWeight: 600 }}>
            Back to Journal
          </a>
        </div>
      </div>

      {/* Annotation Coverage Warning */}
      {coveragePct < 50 && (
        <div style={{ background: '#1A1000', border: '1px solid #854D0E', borderRadius: '8px', padding: '14px 20px', marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: '13px', fontWeight: 600, color: '#FCD34D', marginBottom: '3px' }}>
              Low annotation coverage ({coveragePct}%) — pattern data is incomplete
            </div>
            <div style={{ fontSize: '12px', color: '#92400E' }}>
              {unannotated?.unannotated_count} trades need review. Setup analysis, emotion patterns, and execution coaching require annotated data.
            </div>
          </div>
          <a href="/v2/journal" style={{ background: '#92400E', border: '1px solid #B45309', color: '#FCD34D', padding: '8px 16px', borderRadius: '6px', fontSize: '12px', textDecoration: 'none', fontWeight: 600, whiteSpace: 'nowrap' }}>
            Review Now
          </a>
        </div>
      )}

      {/* Coverage bar */}
      <div style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: '8px', padding: '14px 20px', marginBottom: '20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <span style={{ fontSize: '11px', color: GREY, letterSpacing: '0.08em', fontWeight: 600 }}>ANNOTATION COVERAGE</span>
          <span style={{ fontSize: '13px', fontWeight: 700, color: coveragePct >= 80 ? GREEN : coveragePct >= 40 ? AMBER : RED }}>{reviewedCount}/{totalCount} ({coveragePct}%)</span>
        </div>
        <div style={{ height: '8px', background: BORDER, borderRadius: '4px', overflow: 'hidden' }}>
          <div style={{ width: `${coveragePct}%`, height: '100%', background: coveragePct >= 80 ? GREEN : coveragePct >= 40 ? AMBER : '#EF4444', borderRadius: '4px', transition: 'width 1s ease' }} />
        </div>
      </div>

      {/* Core metrics */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: '12px', marginBottom: '20px' }}>
        <StatCard label="NET P&L" value={fmt$(s.net_pnl)} color={s.net_pnl >= 0 ? GREEN : RED} sub={`${s.total_trades} trades`} />
        <StatCard label="WIN RATE" value={`${s.win_rate_pct}%`} color={BLUE} sub={`${s.wins}W / ${s.losses}L`} />
        <StatCard label="PROFIT FACTOR" value={s.profit_factor} color={s.profit_factor >= 2 ? GREEN : s.profit_factor >= 1 ? AMBER : RED} sub="gross win / gross loss" />
        <StatCard label="EXPECTANCY" value={`${fmt$(s.trade_expectancy)}/trade`} color={s.trade_expectancy >= 0 ? GREEN : RED} sub="avg $ per trade" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: '12px', marginBottom: '24px' }}>
        <StatCard label="AVG WINNER" value={fmt$(s.avg_winner)} color={GREEN} />
        <StatCard label="AVG LOSER" value={fmt$(s.avg_loser)} color={RED} />
        <StatCard label="LARGEST WIN" value={fmt$(s.largest_win)} color={GREEN} />
        <StatCard label="LARGEST LOSS" value={fmt$(s.largest_loss)} color={RED} />
      </div>

      {/* Trade Type + Symbol */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '20px' }}>
        <div style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: '8px', padding: '16px' }}>
          <SectionTitle>P&L BY TRADE TYPE</SectionTitle>
          {(report?.by_trade_type || []).map((t: any) => (
            <MiniBar key={t.trade_type} label={t.trade_type} value={t.net_pnl}
              max={Math.max(...(report?.by_trade_type || []).map((v: any) => Math.abs(v.net_pnl)))}
              color={t.net_pnl >= 0 ? GREEN : RED} count={t.trades} />
          ))}
        </div>
        <div style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: '8px', padding: '16px' }}>
          <SectionTitle>P&L BY SYMBOL (TOP 10)</SectionTitle>
          {(report?.by_symbol || []).slice(0, 10).map((s: any) => (
            <MiniBar key={s.symbol} label={`${s.symbol} (${s.win_rate_pct?.toFixed(0)}% WR)`}
              value={s.net_pnl}
              max={Math.max(...(report?.by_symbol || []).slice(0, 10).map((v: any) => Math.abs(v.net_pnl)))}
              color={s.net_pnl >= 0 ? GREEN : RED} count={s.trades} />
          ))}
        </div>
      </div>

      {/* Monthly P&L */}
      <div style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: '8px', padding: '16px', marginBottom: '20px' }}>
        <SectionTitle>MONTHLY P&L</SectionTitle>
        <div style={{ height: '180px' }}>
          <Bar
            data={{
              labels: (report?.monthly || []).map((m: any) => m.month),
              datasets: [{ data: (report?.monthly || []).map((m: any) => m.net_pnl),
                backgroundColor: (report?.monthly || []).map((m: any) => m.net_pnl >= 0 ? GREEN : RED),
                borderRadius: 3, maxBarThickness: 36 }],
            }}
            options={{
              responsive: true, maintainAspectRatio: false,
              plugins: { legend: { display: false }, tooltip: { ...tooltipOpts, callbacks: { label: (ctx: any) => `P&L: ${fmt$((report?.monthly || [])[ctx.dataIndex]?.net_pnl)} | ${(report?.monthly || [])[ctx.dataIndex]?.trades} trades` } } },
              scales: {
                x: { ticks: { color: GREY, font: { size: 9 } }, grid: { display: false }, border: { display: false } },
                y: { ticks: { color: GREY, font: { size: 9 }, callback: (v: any) => `$${(v / 1000).toFixed(0)}K` }, grid: { color: BORDER }, border: { display: false } },
              },
            }}
          />
        </div>
      </div>

      {/* RSI Histogram */}
      {(report?.rsi_histogram || []).length > 0 && (
        <div style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: '8px', padding: '16px', marginBottom: '20px' }}>
          <SectionTitle>ENTRY RSI DISTRIBUTION (BACKTEST)</SectionTitle>
          <div style={{ height: '180px' }}>
            <Bar
              data={{
                labels: report.rsi_histogram.map((b: any) => b.bucket),
                datasets: [{ data: report.rsi_histogram.map((b: any) => b.count),
                  backgroundColor: report.rsi_histogram.map((b: any) => b.avg_pnl >= 0 ? GREEN : RED),
                  borderRadius: 3, maxBarThickness: 48 }],
              }}
              options={{
                responsive: true, maintainAspectRatio: false,
                plugins: { legend: { display: false }, tooltip: { ...tooltipOpts, callbacks: { label: (ctx: any) => { const b = report.rsi_histogram[ctx.dataIndex]; return `${b?.count} entries | Avg P&L: ${fmt$(b?.avg_pnl)}` } } } },
                scales: {
                  x: { ticks: { color: '#94A3B8', font: { size: 10 } }, grid: { display: false }, border: { display: false } },
                  y: { ticks: { color: GREY, font: { size: 9 } }, grid: { color: BORDER }, border: { display: false } },
                },
              }}
            />
          </div>
          <div style={{ fontSize: '11px', color: AMBER, marginTop: '8px' }}>
            {(() => {
              const total = report.rsi_histogram.reduce((s: number, b: any) => s + b.count, 0)
              const highRsi = report.rsi_histogram.filter((b: any) => b.bucket.includes('70') || b.bucket.includes('80') || b.bucket.includes('Overbought')).reduce((s: number, b: any) => s + b.count, 0)
              return total > 0 ? `${((highRsi / total) * 100).toFixed(0)}% of entries had RSI above 65` : ''
            })()}
          </div>
        </div>
      )}

      {/* Grade Distribution */}
      {(report?.backtest_grades || []).length > 0 && (
        <div style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: '8px', padding: '16px', marginBottom: '20px' }}>
          <SectionTitle>ENTRY & EXIT GRADE DISTRIBUTION</SectionTitle>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
            {[{ title: 'Entry Grades', grades: entryGrades }, { title: 'Exit Grades', grades: exitGrades }].map(({ title, grades }) => (
              <div key={title}>
                <div style={{ fontSize: '12px', color: '#94A3B8', fontWeight: 600, marginBottom: '10px' }}>{title}</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '6px' }}>
                  {['A', 'B', 'C', 'D'].map(g => (
                    <div key={g} style={{
                      background: `${gradeColors[g]}15`, border: `1px solid ${gradeColors[g]}40`,
                      borderRadius: '6px', padding: '10px', textAlign: 'center'
                    }}>
                      <div style={{ fontSize: '18px', fontWeight: 700, color: gradeColors[g] }}>{grades[g]}</div>
                      <div style={{ fontSize: '10px', color: GREY, marginTop: '2px' }}>Grade {g}</div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
          {entryGrades.D > 0 && (
            <div style={{ fontSize: '11px', color: RED, marginTop: '10px' }}>
              {entryGrades.D} D-grade entries ({Math.round(entryGrades.D / Math.max(Object.values(entryGrades).reduce((a, b) => a + b, 0), 1) * 100)}%) — entering overbought, no volume confirmation
            </div>
          )}
        </div>
      )}

      {/* Coaching Insights from API */}
      {(report?.coaching_insights || []).length > 0 && (
        <div style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: '8px', padding: '16px', marginBottom: '20px' }}>
          <SectionTitle>DATA-DRIVEN COACHING</SectionTitle>
          <div style={{ display: 'grid', gap: '10px' }}>
            {report.coaching_insights.map((c: any, i: number) => {
              const borderColor = c.severity === 'high' ? RED : c.severity === 'medium' ? AMBER : BLUE
              return (
                <div key={i} style={{ background: '#0F172A', borderLeft: `3px solid ${borderColor}`, borderRadius: '4px', padding: '12px 16px' }}>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
                    <span style={{ fontSize: '9px', fontWeight: 700, padding: '2px 6px', borderRadius: '3px',
                      background: c.severity === 'high' ? '#1F0D0D' : c.severity === 'medium' ? '#1F1800' : '#0D1426',
                      color: borderColor, letterSpacing: '0.08em', flexShrink: 0, marginTop: '2px' }}>
                      {c.severity.toUpperCase()}
                    </span>
                    <div>
                      <div style={{ color: '#E2E8F0', fontWeight: 700, fontSize: '13px' }}>{c.title}</div>
                      <div style={{ color: '#94A3B8', fontSize: '12px', marginTop: '4px', lineHeight: '1.5' }}>{c.body}</div>
                      <div style={{ color: BLUE, fontSize: '11px', marginTop: '6px', fontStyle: 'italic' }}>{c.action}</div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Backtest Coaching Bullets */}
      {btAnalytics?.coaching_bullets?.length > 0 && (
        <div style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: '8px', padding: '16px', marginBottom: '20px' }}>
          <SectionTitle>BACKTEST INSIGHTS</SectionTitle>
          <div style={{ display: 'grid', gap: '10px' }}>
            {btAnalytics.coaching_bullets.map((bullet: string, i: number) => (
              <div key={i} style={{ background: '#0F172A', borderLeft: `3px solid ${AMBER}`, borderRadius: '4px', padding: '12px 16px' }}>
                <div style={{ color: '#E2E8F0', fontSize: '12px', lineHeight: '1.6' }}>{bullet}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Best Entries & Worst Exits */}
      {btAnalytics?.has_data && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '20px' }}>
          {(btAnalytics.best_entries || []).length > 0 && (
            <div style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: '8px', padding: '16px' }}>
              <SectionTitle>TOP TRADES BY P&L</SectionTitle>
              {btAnalytics.best_entries.slice(0, 8).map((e: any) => (
                <div key={e.trade_key} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '5px 0', borderBottom: '1px solid #0F172A', fontSize: '11px' }}>
                  <span style={{ fontWeight: 700, color: BLUE, minWidth: '50px' }}>{e.symbol}</span>
                  <span style={{ padding: '1px 6px', borderRadius: '3px', fontWeight: 700, fontSize: '10px',
                    background: e.entry_grade === 'A' ? '#0D1F0D' : e.entry_grade === 'B' ? '#0D1A2F' : e.entry_grade === 'C' ? '#1A1500' : '#1F0D0D',
                    color: e.entry_grade === 'A' ? GREEN : e.entry_grade === 'B' ? BLUE : e.entry_grade === 'C' ? AMBER : RED
                  }}>{e.entry_grade}</span>
                  <span style={{ color: GREY }}>RSI {e.entry_rsi?.toFixed(0) ?? '?'}</span>
                  <span style={{ marginLeft: 'auto', fontWeight: 700, color: e.actual_pnl >= 0 ? GREEN : RED }}>{fmt$(e.actual_pnl)}</span>
                </div>
              ))}
            </div>
          )}
          {(btAnalytics.worst_exits || []).length > 0 && (
            <div style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: '8px', padding: '16px' }}>
              <SectionTitle>MOST LEFT ON TABLE (20D)</SectionTitle>
              {btAnalytics.worst_exits.map((e: any) => (
                <div key={e.trade_key} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '5px 0', borderBottom: '1px solid #0F172A', fontSize: '11px' }}>
                  <span style={{ fontWeight: 700, color: BLUE, minWidth: '50px' }}>{e.symbol}</span>
                  <span style={{ padding: '1px 6px', borderRadius: '3px', fontWeight: 700, fontSize: '10px',
                    background: '#1F0D0D', color: RED }}>{e.exit_grade}</span>
                  <span style={{ color: GREY }}>exit ${e.actual_exit_price?.toFixed(2)} → max ${e.max_price_20d_after?.toFixed(2)}</span>
                  <span style={{ marginLeft: 'auto', fontWeight: 700, color: RED }}>{fmt$(e.left_on_table_20d)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Left on Table by Type */}
      {btAnalytics?.left_on_table_by_type?.length > 0 && (
        <div style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: '8px', padding: '16px', marginBottom: '20px' }}>
          <SectionTitle>$ LEFT ON TABLE BY TRADE TYPE</SectionTitle>
          {btAnalytics.left_on_table_by_type.map((t: any) => (
            <MiniBar key={t.trade_type} label={`${t.trade_type} (${t.count} trades)`}
              value={t.total_left || 0}
              max={Math.max(...btAnalytics.left_on_table_by_type.map((v: any) => Math.abs(v.total_left || 0)))}
              color={RED} count={t.count} />
          ))}
        </div>
      )}

      {/* Setup Performance — only if annotated data exists */}
      {(report?.setup_performance || []).length >= 2 ? (
        <div style={{ background: BG, border: `1px solid ${BORDER}`, borderRadius: '8px', padding: '16px', marginBottom: '20px' }}>
          <SectionTitle>SETUP PERFORMANCE ({reviewedCount} annotated trades)</SectionTitle>
          {report.setup_performance.map((s: any) => (
            <div key={s.setup} style={{ display: 'flex', alignItems: 'center', padding: '7px 0', borderBottom: '1px solid #0F172A' }}>
              <span style={{ minWidth: '180px', fontSize: '12px', color: '#94A3B8', textTransform: 'capitalize' }}>{s.setup?.replace(/_/g, ' ')}</span>
              <span style={{ minWidth: '50px', fontSize: '11px', color: GREY }}>{s.count} trades</span>
              <span style={{ minWidth: '60px', fontSize: '11px', color: BLUE }}>{Math.round(s.wins / Math.max(s.count, 1) * 100)}% WR</span>
              <span style={{ fontSize: '12px', fontWeight: 700, color: s.avg_pnl >= 0 ? GREEN : RED, marginLeft: 'auto' }}>
                {fmt$(s.avg_pnl)} avg
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div style={{ background: '#0F172A', border: `1px dashed ${BORDER}`, borderRadius: '8px', padding: '24px', textAlign: 'center', marginBottom: '20px' }}>
          <div style={{ fontSize: '14px', color: GREY, marginBottom: '8px' }}>Setup analysis unlocks at 5+ annotated trades</div>
          <div style={{ fontSize: '12px', color: '#475569' }}>Currently {reviewedCount} annotated</div>
          <a href="/v2/journal" style={{ display: 'inline-block', marginTop: '12px', background: '#1E3A5F', color: BLUE, textDecoration: 'none', padding: '8px 20px', borderRadius: '6px', fontSize: '12px', fontWeight: 600 }}>
            Annotate trades
          </a>
        </div>
      )}
    </div>
  )
}
