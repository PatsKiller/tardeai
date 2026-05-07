import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import { DoughnutChart, BarChartJS } from '../components/charts'
import { useApi } from '../hooks/useApi'

interface SetupRow { setup_name: string; n: number; avg_r: number | null; avg_exec: number | null; avg_sizing: number | null; well_exec_rate: number | null; plan_follow_rate: number | null }
interface TagRow { tag: string; n: number }
interface EmotionRow { emotion_before?: string; emotion_during?: string; n: number }
interface TfRow { timeframe: string; n: number; avg_exec: number | null; well_exec_rate: number | null }
interface MonthRow { month: string; n: number; avg_exec: number | null; avg_sizing: number | null; well_exec_rate: number | null }
interface FamilyRow { family: string; n: number; avg_exec: number | null; well_exec_rate: number | null }
interface SymbolRow { symbol: string; review_count: number; avg_exec: number | null; well_exec_rate: number | null; setups_used: string[] | null }
interface AnalyticsData {
  total_reviews: number; avg_execution: number | null; avg_sizing: number | null
  well_executed_rate: number | null; plan_follow_rate: number | null; has_data: boolean
  by_setup: SetupRow[]; by_timeframe: TfRow[]
  emotion_before: EmotionRow[]; emotion_during: EmotionRow[]
  mistake_tags: TagRow[]; strength_tags: TagRow[]
  monthly_trend: MonthRow[]; by_setup_family: FamilyRow[]; reviewed_symbols: SymbolRow[]
  by_catalyst: { catalyst_type: string; n: number; avg_exec: number | null; well_exec_rate: number | null }[]
  insights: { type: string; text: string }[]
}

const lbl: React.CSSProperties = { fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '0.3px' }

function pct(v: number | null | undefined): string { return v != null ? `${(v * 100).toFixed(0)}%` : '—' }
function num(v: number | null | undefined, d = 1): string { return v != null ? v.toFixed(d) : '—' }

export default function JournalAnalytics() {
  const navigate = useNavigate()
  const { data } = useApi<AnalyticsData>('/api/v2/journal/analytics')

  if (!data) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading analytics...</div>

  if (!data.has_data) {
    return (
      <>
        <PageHeader title="Journal Analytics" subtitle="Trade review intelligence — requires 3+ reviewed trades per setup type for pattern insights" />
        <Card>
          <div style={{ color: 'var(--text3)', textAlign: 'center', padding: 40 }}>
            <div style={{ fontSize: 14, marginBottom: 8 }}>No reviewed trades yet</div>
            <div style={{ fontSize: 11 }}>Open a trade in the Journal, click the Review or Psychology tab, and save your assessment. Analytics will appear here as reviews accumulate.</div>
          </div>
        </Card>
      </>
    )
  }

  return (
    <>
      <PageHeader title="Journal Analytics" subtitle={`${data.total_reviews} trade${data.total_reviews !== 1 ? 's' : ''} reviewed · ${data.total_reviews < 10 ? 'Need 10+ reviews for reliable patterns' : data.total_reviews < 30 ? 'Good sample — patterns becoming meaningful' : 'Strong sample — patterns are statistically useful'}`} />

      {/* CTA to review unreviewed trades */}
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10, padding: '8px 14px', background: 'rgba(74,144,244,0.06)', border: '1px solid rgba(74,144,244,0.15)', borderRadius: 10, fontSize: 11 }}>
        <span style={{ color: 'var(--accent)', fontWeight: 600 }}>Improve your edge:</span>
        <span style={{ color: 'var(--text2)' }}>Review untagged trades in the Journal — the more reviews, the better the pattern detection.</span>
        <button onClick={() => navigate('/journal')} style={{ marginLeft: 'auto', padding: '3px 12px', fontSize: 10, border: '1px solid var(--accent)', borderRadius: 'var(--radius)', background: 'var(--accent-dim)', color: 'var(--accent)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Open Journal</button>
      </div>

      {/* Summary strip */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <MetricTile label="Reviews" value={String(data.total_reviews)} />
        <MetricTile label="Avg Execution" value={num(data.avg_execution)} delta="1-5 scale · entry/exit/plan" deltaColor={data.avg_execution != null && data.avg_execution >= 4 ? 'var(--green)' : data.avg_execution != null && data.avg_execution >= 3 ? 'var(--amber)' : 'var(--text2)'} />
        <MetricTile label="Avg Sizing" value={num(data.avg_sizing)} deltaColor={data.avg_sizing != null && data.avg_sizing >= 4 ? 'var(--green)' : 'var(--text2)'} />
        <MetricTile label="Well Executed" value={pct(data.well_executed_rate)} deltaColor={data.well_executed_rate != null && data.well_executed_rate >= 0.7 ? 'var(--green)' : 'var(--amber)'} />
        <MetricTile label="Followed Plan" value={pct(data.plan_follow_rate)} deltaColor={data.plan_follow_rate != null && data.plan_follow_rate >= 0.7 ? 'var(--green)' : 'var(--amber)'} />
      </div>

      {/* Visual Charts */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
        {/* Emotion Before - Doughnut */}
        {data.emotion_before.length > 0 && (
          <div>
            <SectionHeader title="Emotion Distribution (Before Trade)" />
            <Card>
              <DoughnutChart
                labels={data.emotion_before.map(e => e.emotion_before || 'unknown')}
                data={data.emotion_before.map(e => e.n)}
                height={180}
              />
            </Card>
          </div>
        )}

        {/* Mistake Tags - Bar */}
        {data.mistake_tags.length > 0 && (
          <div>
            <SectionHeader title="Most Common Mistakes" />
            <Card>
              <BarChartJS
                labels={data.mistake_tags.slice(0, 8).map(m => m.tag)}
                data={data.mistake_tags.slice(0, 8).map(m => m.n)}
                colors={data.mistake_tags.slice(0, 8).map(() => '#f6465d')}
                height={180}
              />
            </Card>
          </div>
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
        {/* Setup Type Distribution - Doughnut */}
        {data.by_setup.length > 0 && (
          <div>
            <SectionHeader title="Setup Type Distribution" />
            <Card>
              <DoughnutChart
                labels={data.by_setup.map(s => s.setup_name)}
                data={data.by_setup.map(s => s.n)}
                height={180}
              />
            </Card>
          </div>
        )}

        {/* Trades by Timeframe - Bar */}
        {data.by_timeframe.length > 0 && (
          <div>
            <SectionHeader title="Trades by Timeframe" />
            <Card>
              <BarChartJS
                labels={data.by_timeframe.map(t => t.timeframe)}
                data={data.by_timeframe.map(t => t.n)}
                colors={data.by_timeframe.map(() => '#4a90f4')}
                height={180}
              />
            </Card>
          </div>
        )}
      </div>

      {/* Pattern insights */}
      {(data.insights?.length ?? 0) > 0 && (
        <div style={{ marginBottom: 12 }}>
          <SectionHeader title="Pattern Insights" count={data.insights.length} />
          <Card>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {data.insights.map((ins, i) => {
                const iconMap: Record<string, string> = { guidance: '\u{1f4a1}', setup: '\u{1f3af}', discipline: '\u26a0\ufe0f', strength: '\u2705', warning: '\u{1f6d1}', mistake: '\u274c', timeframe: '\u23f0', gap: '\u{1f50d}', keep: '\u{1f7e2}', stop: '\u{1f534}', review: '\u{1f4cb}' }
                const colorMap: Record<string, string> = { guidance: 'var(--accent)', setup: 'var(--text1)', discipline: 'var(--amber)', strength: 'var(--green)', warning: 'var(--red)', mistake: 'var(--red)', timeframe: 'var(--accent)', gap: 'var(--amber)', keep: 'var(--green)', stop: 'var(--red)', review: 'var(--accent)' }
                return (
                  <div key={i} style={{ display: 'flex', gap: 8, padding: '6px 8px', borderRadius: 'var(--radius)', background: 'var(--bg3)', borderLeft: `3px solid ${colorMap[ins.type] || 'var(--text3)'}` }}>
                    <span style={{ fontSize: 14, flexShrink: 0 }}>{iconMap[ins.type] || '\u{1f4cb}'}</span>
                    <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5 }}>{ins.text}</div>
                  </div>
                )
              })}
            </div>
          </Card>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
        {/* By Setup */}
        <div>
          <SectionHeader title="Performance by Setup" count={data.by_setup.length} />
          <Card>
            {data.by_setup.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {data.by_setup.map(s => (
                  <div key={s.setup_name} style={{ display: 'flex', gap: 8, padding: '6px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, alignItems: 'center', opacity: s.n < 3 ? 0.5 : 1 }}>
                    <span style={{ fontWeight: 700, color: 'var(--text0)', width: 100 }}>{s.setup_name}</span>
                    <span style={{ color: s.n < 3 ? 'var(--amber)' : 'var(--text3)' }}>{s.n} trade{s.n !== 1 ? 's' : ''}{s.n < 3 ? ' (needs 3+)' : ''}</span>
                    {s.avg_r != null && <span>Avg R: <strong style={{ color: s.avg_r >= 0 ? 'var(--green)' : 'var(--red)' }}>{s.avg_r.toFixed(2)}</strong></span>}
                    {s.avg_exec != null && <span>Exec: <strong>{s.avg_exec.toFixed(1)}</strong>/5</span>}
                    {s.well_exec_rate != null && <span style={{ color: s.well_exec_rate >= 0.7 ? 'var(--green)' : 'var(--amber)' }}>{pct(s.well_exec_rate)} well</span>}
                  </div>
                ))}
              </div>
            ) : <div style={{ color: 'var(--text3)', fontSize: 10, padding: 8 }}>No setup data yet. Tag trades with setup names in the Journal Review tab.</div>}
          </Card>
        </div>

        {/* By Timeframe */}
        <div>
          <SectionHeader title="Performance by Timeframe" count={data.by_timeframe.length} />
          <Card>
            {data.by_timeframe.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {data.by_timeframe.map(t => (
                  <div key={t.timeframe} style={{ display: 'flex', gap: 8, padding: '6px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, alignItems: 'center' }}>
                    <span style={{ fontWeight: 700, color: 'var(--text0)', width: 100 }}>{t.timeframe}</span>
                    <span style={{ color: 'var(--text3)' }}>{t.n} trade{t.n !== 1 ? 's' : ''}</span>
                    {t.avg_exec != null && <span>Exec: <strong>{t.avg_exec.toFixed(1)}</strong>/5</span>}
                    {t.well_exec_rate != null && <span style={{ color: t.well_exec_rate >= 0.7 ? 'var(--green)' : 'var(--amber)' }}>{pct(t.well_exec_rate)} well</span>}
                  </div>
                ))}
              </div>
            ) : <div style={{ color: 'var(--text3)', fontSize: 10, padding: 8 }}>No timeframe data yet.</div>}
          </Card>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
        {/* Emotions */}
        <div>
          <SectionHeader title="Emotion Before Trade" count={data.emotion_before.length} />
          <Card>
            {data.emotion_before.length > 0 ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {data.emotion_before.map(e => (
                  <div key={e.emotion_before} style={{ padding: '4px 10px', borderRadius: 'var(--radius)', background: 'var(--bg3)', fontSize: 10 }}>
                    <span style={{ color: 'var(--text1)' }}>{e.emotion_before}</span>
                    <span style={{ marginLeft: 4, fontWeight: 700, color: 'var(--text0)' }}>{e.n}</span>
                  </div>
                ))}
              </div>
            ) : <div style={{ color: 'var(--text3)', fontSize: 10, padding: 8 }}>No emotion data yet. Tag emotions in the Journal Psychology tab.</div>}
          </Card>
        </div>

        <div>
          <SectionHeader title="Emotion During Trade" count={data.emotion_during.length} />
          <Card>
            {data.emotion_during.length > 0 ? (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {data.emotion_during.map(e => (
                  <div key={e.emotion_during} style={{ padding: '4px 10px', borderRadius: 'var(--radius)', background: 'var(--bg3)', fontSize: 10 }}>
                    <span style={{ color: 'var(--text1)' }}>{e.emotion_during}</span>
                    <span style={{ marginLeft: 4, fontWeight: 700, color: 'var(--text0)' }}>{e.n}</span>
                  </div>
                ))}
              </div>
            ) : <div style={{ color: 'var(--text3)', fontSize: 10, padding: 8 }}>No emotion data yet.</div>}
          </Card>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {/* Mistakes */}
        <div>
          <SectionHeader title="Top Mistake Tags" count={data.mistake_tags.length} />
          <Card>
            {data.mistake_tags.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                {data.mistake_tags.map(m => {
                  const maxN = Math.max(...data.mistake_tags.map(t => t.n), 1)
                  return (
                    <div key={m.tag} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10 }}>
                      <span style={{ width: 90, color: 'var(--red)', fontWeight: 600 }}>{m.tag}</span>
                      <div style={{ flex: 1, height: 8, background: 'var(--bg3)', borderRadius: 4, overflow: 'hidden' }}>
                        <div style={{ width: `${(m.n / maxN) * 100}%`, height: '100%', background: 'var(--red)', opacity: 0.6, borderRadius: 4 }} />
                      </div>
                      <span style={{ width: 20, textAlign: 'right', fontWeight: 700 }}>{m.n}</span>
                    </div>
                  )
                })}
              </div>
            ) : <div style={{ color: 'var(--text3)', fontSize: 10, padding: 8 }}>No mistake tags yet. Tag mistakes in the Journal Psychology tab.</div>}
          </Card>
        </div>

        {/* Strengths */}
        <div>
          <SectionHeader title="Top Strength Tags" count={data.strength_tags.length} />
          <Card>
            {data.strength_tags.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                {data.strength_tags.map(s => {
                  const maxN = Math.max(...data.strength_tags.map(t => t.n), 1)
                  return (
                    <div key={s.tag} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10 }}>
                      <span style={{ width: 90, color: 'var(--green)', fontWeight: 600 }}>{s.tag}</span>
                      <div style={{ flex: 1, height: 8, background: 'var(--bg3)', borderRadius: 4, overflow: 'hidden' }}>
                        <div style={{ width: `${(s.n / maxN) * 100}%`, height: '100%', background: 'var(--green)', opacity: 0.6, borderRadius: 4 }} />
                      </div>
                      <span style={{ width: 20, textAlign: 'right', fontWeight: 700 }}>{s.n}</span>
                    </div>
                  )
                })}
              </div>
            ) : <div style={{ color: 'var(--text3)', fontSize: 10, padding: 8 }}>No strength tags yet.</div>}
          </Card>
        </div>
      </div>

      {/* Monthly execution trend */}
      {(data.monthly_trend?.length ?? 0) > 0 && (
        <>
          <SectionHeader title="Monthly Execution Trend" count={data.monthly_trend.length} />
          <Card>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {data.monthly_trend.map(m => (
                <div key={m.month} style={{ padding: '8px 12px', background: 'var(--bg3)', borderRadius: 'var(--radius)', minWidth: 100, textAlign: 'center' }}>
                  <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text0)' }}>{m.month}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>{m.n} review{m.n !== 1 ? 's' : ''}</div>
                  {m.avg_exec != null && <div style={{ fontSize: 12, fontWeight: 700, color: m.avg_exec >= 4 ? 'var(--green)' : m.avg_exec >= 3 ? 'var(--amber)' : 'var(--red)', marginTop: 4 }}>{m.avg_exec.toFixed(1)}</div>}
                  <div style={{ fontSize: 8, color: 'var(--text3)' }}>exec avg</div>
                  {m.well_exec_rate != null && <div style={{ fontSize: 9, color: m.well_exec_rate >= 0.7 ? 'var(--green)' : 'var(--amber)' }}>{pct(m.well_exec_rate)} well</div>}
                </div>
              ))}
            </div>
          </Card>
        </>
      )}

      {/* Setup family rollups */}
      {(data.by_setup_family?.length ?? 0) > 0 && (
        <>
          <SectionHeader title="By Setup Family" count={data.by_setup_family.length} />
          <Card>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {data.by_setup_family.map(f => (
                <div key={f.family} style={{ display: 'flex', gap: 8, padding: '5px 0', borderBottom: '1px solid var(--border-subtle)', fontSize: 10, alignItems: 'center' }}>
                  <span style={{ fontWeight: 700, color: 'var(--text0)', width: 120 }}>{f.family}</span>
                  <span style={{ color: 'var(--text3)' }}>{f.n} trade{f.n !== 1 ? 's' : ''}</span>
                  {f.avg_exec != null && <span>Exec: <strong>{f.avg_exec.toFixed(1)}</strong>/5</span>}
                  {f.well_exec_rate != null && <span style={{ color: f.well_exec_rate >= 0.7 ? 'var(--green)' : 'var(--amber)' }}>{pct(f.well_exec_rate)} well executed</span>}
                </div>
              ))}
            </div>
          </Card>
        </>
      )}

      {/* Symbol review history (for recovery cross-reference) */}
      {(data.reviewed_symbols?.length ?? 0) > 0 && (
        <>
          <SectionHeader title="Reviewed Symbols" count={data.reviewed_symbols.length} />
          <Card compact>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {data.reviewed_symbols.map(s => (
                <button key={s.symbol} onClick={() => navigate(`/journal?symbol=${s.symbol}`)} style={{ padding: '4px 10px', background: 'var(--bg3)', borderRadius: 'var(--radius)', fontSize: 10, border: '1px solid var(--border-subtle)', cursor: 'pointer', textAlign: 'left' }}>
                  <span style={{ fontWeight: 700, color: 'var(--accent)' }}>{s.symbol}</span>
                  <span style={{ marginLeft: 4, color: 'var(--text3)' }}>{s.review_count}x</span>
                  {s.avg_exec != null && <span style={{ marginLeft: 4, color: s.avg_exec >= 4 ? 'var(--green)' : 'var(--text2)' }}>exec {s.avg_exec.toFixed(1)}</span>}
                  {s.setups_used && s.setups_used.length > 0 && <span style={{ marginLeft: 4, color: 'var(--text3)', fontSize: 8 }}>{s.setups_used.join(', ')}</span>}
                </button>
              ))}
            </div>
          </Card>
        </>
      )}

      {data.total_reviews < 5 && (
        <Card compact>
          <div style={{ color: 'var(--text3)', fontSize: 10, textAlign: 'center', padding: 8 }}>
            Analytics improve with more reviewed trades. You have {data.total_reviews} review{data.total_reviews !== 1 ? 's' : ''} — aim for 10+ to see meaningful patterns. Open trades in the Journal and use the Review/Psychology tabs.
          </div>
        </Card>
      )}
    </>
  )
}
