import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import { DoughnutChart, BarChartJS } from '../components/charts'
import { useApi } from '../hooks/useApi'
import { fmt$, timeAgo } from '../lib/format'
import AccountBadge from '../components/AccountBadge'

interface RebalanceData {
  generated_at: string
  status: string
  ground_truth: { as_of?: string; total_portfolio?: number; recent_trade_count?: number }
  recommendations?: { symbol: string; action: string; rationale: string; severity?: string; account?: string; shares?: number; reason?: string }[]
  computed?: boolean
  account_summary?: { account: string; total_value: number; position_count: number; cash: number; value?: number; pct?: number }[]
  observations?: { type: string; account: string; message: string; data?: Record<string, unknown> }[]
  suggestions?: { id: string; type: string; account: string; rationale: string; confidence: string; do_not_apply_if: string }[]
  yaml_health_score?: number | null
  yaml_health_notes?: string
  executive_lines?: string[]
  v_strategy_lines?: string[]
  bond_strategy_lines?: string[]
  summary?: string
  computed_values?: { total_value?: number; income_target?: number; income_current?: number; income_gap?: number }
  model_used?: string | null
  is_stale?: boolean
  stale_note?: string | null
}

export default function Rebalance() {
  const navigate = useNavigate()
  const { data, refetch } = useApi<RebalanceData>('/api/v2/rebalance')
  const [refreshing, setRefreshing] = useState(false)
  const [refreshMsg, setRefreshMsg] = useState('')

  if (!data) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading rebalance...</div>

  const genDate = data.generated_at ? new Date(data.generated_at) : null
  const genLabel = genDate ? `${genDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })} (${timeAgo(data.generated_at)})` : 'Pending'
  const stale = genDate ? (Date.now() - genDate.getTime()) > 7 * 86400000 : true

  const handleRefresh = async () => {
    setRefreshing(true)
    setRefreshMsg('')
    try {
      const r = await fetch('/api/v2/rebalance/refresh', { method: 'POST' })
      const d = await r.json()
      if (d.ok) {
        setRefreshMsg('Refresh running — will auto-reload when done...')
        // Poll every 10s until generated_at changes
        const checkInterval = setInterval(() => {
          fetch('/api/v2/rebalance').then(r => r.json()).then(rd => {
            const newGen = (rd.data || rd).generated_at
            if (newGen && newGen !== data.generated_at) {
              clearInterval(checkInterval)
              setRefreshMsg('Done! Reloading...')
              setTimeout(() => { refetch(); setRefreshing(false); setRefreshMsg('') }, 1000)
            }
          }).catch(() => {})
        }, 10000)
        // Safety timeout after 3 min
        setTimeout(() => { clearInterval(checkInterval); refetch(); setRefreshing(false); setRefreshMsg('') }, 180000)
      } else {
        setRefreshMsg(`Failed: ${d.error || 'unknown'}`)
        setRefreshing(false)
      }
    } catch (e) {
      setRefreshMsg(`Error: ${e}`)
      setRefreshing(false)
    }
  }

  return (
    <>
      <PageHeader title="Rebalancing" subtitle="AI + Portfolio Baseline" />
      <div style={{ padding: '8px 14px', marginBottom: 12, background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 8, fontSize: 11, color: 'var(--amber)', fontWeight: 600 }}>
        ⚠️ Advisory only — all actions require manual execution at your broker (Fidelity/Schwab). This app does not place or cancel orders.
      </div>

      {/* Freshness + model + refresh */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        {stale && (
          <div style={{ padding: '6px 12px', background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 'var(--radius)', fontSize: 10, color: 'var(--amber)', flex: 1 }}>
            Rebalance data is stale (generated {genLabel}).
          </div>
        )}
        {data.model_used && (
          <div style={{ padding: '4px 8px', background: 'var(--accent-dim)', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', fontSize: 9, color: 'var(--accent)' }}>
            LLM: {data.model_used}
          </div>
        )}
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          style={{ padding: '6px 14px', fontSize: 10, fontWeight: 600, border: '1px solid var(--accent)', borderRadius: 'var(--radius)', background: refreshing ? 'var(--bg3)' : 'var(--accent-dim)', color: 'var(--accent)', cursor: refreshing ? 'wait' : 'pointer' }}
        >
          {refreshing ? 'Refreshing...' : '↻ Refresh Rebalance'}
        </button>
        {refreshMsg && <span style={{ fontSize: 10, color: 'var(--text2)' }}>{refreshMsg}</span>}
      </div>

      {/* Key Metrics */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        <MetricTile label="Total Value" value={fmt$(data.computed_values?.total_value ?? data.ground_truth?.total_portfolio ?? 0)} delta={`as of ${data.ground_truth?.as_of || '\u2014'}`} />
        <MetricTile label="Income Current" value={fmt$(data.computed_values?.income_current ?? 0)} deltaColor="var(--green)" />
        <MetricTile label="Income Gap" value={fmt$(data.computed_values?.income_gap ?? 0)} deltaColor={(data.computed_values?.income_gap ?? 0) > 0 ? 'var(--amber)' : 'var(--green)'} />
        <MetricTile label="Recommendations" value={String(data.recommendations?.length ?? 0)} deltaColor={data.recommendations?.length ? 'var(--accent)' : 'var(--text3)'} />
      </div>

      {/* Charts Row */}
      {((data.account_summary?.length ?? 0) > 0 || (data.recommendations?.length ?? 0) > 0) && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
          {(data.account_summary?.length ?? 0) > 0 && (
            <div>
              <SectionHeader title="Account Allocation" />
              <Card>
                <DoughnutChart
                  labels={data.account_summary!.map(a => a.account.replace('schwab_', '').replace('fidelity_', ''))}
                  data={data.account_summary!.map(a => a.pct ?? a.total_value ?? a.value ?? 0)}
                  height={180}
                />
              </Card>
            </div>
          )}
          {(data.recommendations?.length ?? 0) > 0 && (() => {
            const buyCount = data.recommendations!.filter(r => r.action?.toUpperCase().includes('BUY')).length
            const sellCount = data.recommendations!.filter(r => r.action?.toUpperCase().includes('SELL') || r.action?.toUpperCase().includes('TRIM')).length
            return (
              <div>
                <SectionHeader title="BUY vs SELL Recommendations" />
                <Card>
                  <BarChartJS
                    labels={['BUY', 'SELL/TRIM']}
                    data={[buyCount, sellCount]}
                    colors={['#0ecb81', '#f6465d']}
                    height={180}
                  />
                </Card>
              </div>
            )
          })()}
        </div>
      )}

      {/* Executive summary lines */}
      {data.executive_lines && data.executive_lines.length > 0 && (
        <>
          <SectionHeader title="Executive Summary" />
          <Card>
            <ul style={{ margin: 0, padding: '0 0 0 16px', listStyle: 'disc' }}>
              {data.executive_lines.map((line, i) => (
                <li key={i} style={{ color: 'var(--text1)', fontSize: 11, lineHeight: 1.7, marginBottom: 4 }}>{line}</li>
              ))}
            </ul>
          </Card>
        </>
      )}

      {/* Legacy metric row */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 12 }}>
        <MetricTile label="Ground Truth" value={fmt$(data.ground_truth?.total_portfolio ?? 0)} delta={`as of ${data.ground_truth?.as_of || '\u2014'}`} />
        <MetricTile label="Status" value={data.status?.replace(/_/g, ' ') || 'pending'} deltaColor={data.status === 'approved' ? 'var(--green)' : 'var(--amber)'} />
        <MetricTile label="Generated" value={genLabel} deltaColor={stale ? 'var(--amber)' : 'var(--text2)'} />
        <MetricTile label="Review Mode" value="Advisory" delta="manual approval required" />
      </div>

      {/* Summary text */}
      {data.summary && (
        <>
          <SectionHeader title="Summary" />
          <Card>
            <div style={{ color: 'var(--text2)', fontSize: 11, lineHeight: 1.6 }}>
              {data.summary}
            </div>
          </Card>
        </>
      )}

      {/* YAML Health + Observations */}
      {data.yaml_health_score != null && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
          <div style={{ width: 48, height: 48, borderRadius: 999, border: `3px solid ${data.yaml_health_score >= 70 ? 'var(--green)' : data.yaml_health_score >= 50 ? 'var(--amber)' : 'var(--red)'}`, display: 'grid', placeItems: 'center', fontWeight: 800, fontSize: 16, color: data.yaml_health_score >= 70 ? 'var(--green)' : data.yaml_health_score >= 50 ? 'var(--amber)' : 'var(--red)' }}>{data.yaml_health_score}</div>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)' }}>
              YAML Health Score
              <span style={{ fontSize: 9, fontWeight: 400, color: 'var(--text3)', marginLeft: 6 }} title="Measures alignment between portfolio_config.yaml targets vs actual holdings. 100 = all targets met, stops set, no drift. Below 50 = significant config-to-reality gaps — review YAML or run sync.">{data.yaml_health_score >= 70 ? 'Healthy' : data.yaml_health_score >= 50 ? 'Needs attention' : 'Critical drift'}</span>
            </div>
            {data.yaml_health_notes && <div style={{ fontSize: 10, color: 'var(--text2)', maxWidth: 500 }}>{data.yaml_health_notes.slice(0, 150)}</div>}
            <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 2 }}>Config: config/portfolio_config.yaml · Edit via Ops Console or SSH</div>
          </div>
        </div>
      )}

      {(data.observations?.length ?? 0) > 0 && (
        <>
          <SectionHeader title="Analyst Observations" count={data.observations!.length} />
          <Card>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {data.observations!.map((obs, i) => (
                <div key={i} style={{ padding: '8px 10px', borderRadius: 'var(--radius)', background: 'var(--bg3)', borderLeft: `3px solid ${obs.type === 'warning' ? 'var(--amber)' : 'var(--accent)'}` }}>
                  <div style={{ display: 'flex', gap: 6, marginBottom: 3 }}>
                    {obs.account && <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'var(--accent-dim)', color: 'var(--accent)' }}>{obs.account.replace('schwab_', '').replace('fidelity_', '')}</span>}
                    <span style={{ fontSize: 8, fontWeight: 600, color: 'var(--text3)', textTransform: 'uppercase' }}>{obs.type}</span>
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text1)', lineHeight: 1.5 }}>{obs.message}</div>
                </div>
              ))}
            </div>
          </Card>
        </>
      )}

      {(data.suggestions?.length ?? 0) > 0 && (
        <>
          <SectionHeader title="AI Suggestions" count={data.suggestions!.length} />
          <Card>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {data.suggestions!.map((sug, i) => (
                <div key={i} style={{ padding: '8px 10px', borderRadius: 'var(--radius)', background: 'var(--bg3)', borderLeft: `3px solid ${sug.confidence === 'high' ? 'var(--green)' : 'var(--amber)'}` }}>
                  <div style={{ display: 'flex', gap: 6, marginBottom: 3 }}>
                    {sug.account && <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: 'var(--accent-dim)', color: 'var(--accent)' }}>{sug.account.replace('schwab_', '').replace('fidelity_', '')}</span>}
                    <span style={{ fontSize: 8, fontWeight: 600, padding: '1px 5px', borderRadius: 3, background: sug.confidence === 'high' ? 'var(--green-dim)' : 'var(--amber-dim)', color: sug.confidence === 'high' ? 'var(--green)' : 'var(--amber)' }}>{sug.confidence}</span>
                    <span style={{ fontSize: 8, color: 'var(--text3)' }}>{sug.type?.replace(/_/g, ' ')}</span>
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text1)', lineHeight: 1.5 }}>{sug.rationale}</div>
                  {sug.do_not_apply_if && <div style={{ fontSize: 9, color: 'var(--red)', marginTop: 4 }}>Do not apply if: {sug.do_not_apply_if}</div>}
                  <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                    {sug.type === 'update_target' && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'var(--amber-dim)', color: 'var(--amber)' }}>Requires YAML change</span>}
                    {sug.type === 'update_notes' && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'var(--bg3)', color: 'var(--text3)' }}>Config note update</span>}
                    {sug.type === 'trade_action' && <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'var(--green-dim)', color: 'var(--green)' }}>Account-level action</span>}
                    <span style={{ fontSize: 8, padding: '1px 5px', borderRadius: 3, background: 'var(--bg3)', color: 'var(--text3)' }}>Advisory — requires human review</span>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </>
      )}

      {/* Strategy panels */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginTop: 12 }}>
        <div>
          <SectionHeader title="V Concentration / Trim Framework" />
          <Card>
            {data.v_strategy_lines?.length ? data.v_strategy_lines.slice(0, 7).map((line, idx) => (
              <div key={idx} style={{ padding: '6px 0', borderBottom: '1px solid var(--border-subtle)', color: idx === 0 ? 'var(--text0)' : 'var(--text2)', fontSize: 11, fontWeight: idx === 0 ? 600 : 400 }}>{line}</div>
            )) : (
              <div style={{ color: 'var(--text3)', fontSize: 11, padding: 8 }}>No V strategy data. Run rebalance pipeline to generate.</div>
            )}
          </Card>
        </div>
        <div>
          <SectionHeader title="Bond / Ballast Recommendations" />
          <Card>
            {data.bond_strategy_lines?.length ? data.bond_strategy_lines.slice(0, 7).map((line, idx) => (
              <div key={idx} style={{ padding: '6px 0', borderBottom: '1px solid var(--border-subtle)', color: idx === 0 ? 'var(--text0)' : 'var(--text2)', fontSize: 11, fontWeight: idx === 0 ? 600 : 400 }}>{line}</div>
            )) : (
              <div style={{ color: 'var(--text3)', fontSize: 11, padding: 8 }}>No bond strategy data. Run rebalance pipeline to generate.</div>
            )}
          </Card>
        </div>
      </div>

      {/* Recommendations */}
      {data.recommendations && data.recommendations.length > 0 && (
        <>
          <SectionHeader title={data.computed ? 'Computed Recommendations (Live)' : 'Pipeline Recommendations'} count={data.recommendations.length} />
          {data.computed && (
            <div style={{ padding: '4px 10px', background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 'var(--radius)', marginBottom: 8, fontSize: 9, color: 'var(--amber)' }}>
              These recommendations are computed from live portfolio state (concentration, stops, income). Run the rebalance pipeline for deeper AI-generated analysis.
            </div>
          )}
          <Card>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {data.recommendations.map((rec, i) => {
                const sevColor = rec.severity === 'high' ? 'var(--red)' : rec.severity === 'medium' ? 'var(--amber)' : 'var(--text3)'
                const actColor = rec.action?.includes('SELL') ? 'var(--red)' : rec.action?.includes('TRIM') ? 'var(--amber)' : rec.action?.includes('STOP') ? 'var(--amber)' : rec.action?.includes('BUY') ? 'var(--green)' : 'var(--text1)'
                return (
                  <div key={i} style={{ padding: '8px 10px', borderRadius: 'var(--radius)', background: 'var(--bg3)', borderLeft: `3px solid ${sevColor}` }}>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
                      {rec.symbol && <span style={{ fontWeight: 700, fontSize: 12, color: 'var(--text0)' }}>{rec.symbol}</span>}
                      <AccountBadge account={rec.account} />
                      <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3, background: `color-mix(in srgb, ${actColor} 15%, transparent)`, color: actColor, textTransform: 'uppercase' }}>{rec.action}</span>
                      {rec.severity && <span style={{ fontSize: 8, color: sevColor, fontWeight: 600 }}>{rec.severity}</span>}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.5 }}>{rec.rationale}</div>
                  </div>
                )
              })}
            </div>
          </Card>
        </>
      )}

      {/* Account summary with next actions */}
      {(data.account_summary?.length ?? 0) > 0 && (
        <>
          <SectionHeader title="Account Breakdown" count={data.account_summary!.length} />
          <Card compact>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 8 }}>
              {data.account_summary!.map(a => {
                const acctKey = a.account
                const acctRecs = data.recommendations?.filter(r => r.account === acctKey) ?? []
                const buyCount = acctRecs.filter(r => r.action?.toUpperCase().includes('BUY') || r.action?.toUpperCase().includes('ADD')).length
                const sellCount = acctRecs.filter(r => r.action?.toUpperCase().includes('SELL') || r.action?.toUpperCase().includes('TRIM')).length
                const is401k = acctKey.includes('401k')
                return (
                  <div key={acctKey} style={{ padding: '8px 10px', background: 'var(--bg3)', borderRadius: 'var(--radius)' }}>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 4 }}>
                      <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)' }}>{acctKey.replace('schwab_', '').replace('fidelity_', '')}</span>
                      {is401k && <span style={{ fontSize: 8, color: 'var(--text3)' }} title="Managed via Fidelity NetBenefits — trades require manual login">{'\uD83C\uDFE6'}</span>}
                    </div>
                    <div style={{ display: 'flex', gap: 10, fontSize: 10, color: 'var(--text2)' }}>
                      <span>Value: <strong>{fmt$(a.total_value)}</strong></span>
                      <span>{a.position_count} positions</span>
                      {a.cash > 0 && <span>Cash: <strong style={{ color: 'var(--green)' }}>{fmt$(a.cash)}</strong></span>}
                    </div>
                    {acctRecs.length > 0 && (
                      <div style={{ marginTop: 4, fontSize: 9, color: 'var(--text3)' }}>
                        {buyCount > 0 && <span style={{ color: 'var(--green)', marginRight: 8 }}>{buyCount} BUY/ADD</span>}
                        {sellCount > 0 && <span style={{ color: 'var(--red)', marginRight: 8 }}>{sellCount} SELL/TRIM</span>}
                        {is401k && sellCount > 0 && <span style={{ color: 'var(--amber)' }}>Execute via Fidelity</span>}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </Card>
        </>
      )}

      {/* Validation links */}
      <SectionHeader title="Cross-Check" />
      <Card compact>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button onClick={() => navigate('/portfolio')} style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Holdings</button>
          <button onClick={() => navigate('/risk')} style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Risk</button>
          <button onClick={() => navigate('/correlation')} style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Correlation</button>
          <button onClick={() => navigate('/dividends')} style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Dividends</button>
          <button onClick={() => navigate('/attribution')} style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Attribution</button>
          <button onClick={() => navigate('/approvals')} style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--mono)' }}>Approvals</button>
        </div>
      </Card>

      <Card compact>
        <div style={{ color: 'var(--text3)', fontSize: 9 }}>Advisory only — all actions require manual review and approval.</div>
      </Card>
    </>
  )
}
