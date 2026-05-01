import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import DetailDrawer, { DrawerStat, DrawerSection } from '../components/DetailDrawer'
import DataGrid from '../components/DataGrid'
import { DoughnutChart, BarChartJS } from '../components/charts'
import { useApi } from '../hooks/useApi'
import { fmt$, fmtPct, deltaColor } from '../lib/format'

interface Position { symbol: string; market_value: number; stop_price: number | null; current_price: number; distance_pct: number | null; max_loss: number; status: string; triggered: boolean; stop_conf_status?: string; stop_confirmed?: boolean; stop_price_confirmed?: number | null; stop_confirmed_at?: string | null; reminder_count?: number; day_change_pct?: number; has_stop?: boolean; rsi?: number; distance_to_stop_pct?: number }
interface EscItem { symbol: string; max_loss?: number; distance_pct?: number; market_value?: number; account?: string }
interface RiskData { portfolio_heat_pct: number; total_risk_dollars: number; pct_protected: number; total_protected_mv: number; total_unprotected_mv: number; position_count: number; positions: Position[]; stops: Record<string, { stop_price: number | null; triggered: boolean }>; escalation?: { danger: EscItem[]; warning: EscItem[]; unprotected: EscItem[] } }

export default function Risk() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const { data: r } = useApi<RiskData>('/api/v2/risk')
  const [selectedPos, setSelectedPos] = useState<Position | null>(null)

  useEffect(() => {
    const symbol = params.get('symbol')?.toUpperCase()
    if (!symbol || !r?.positions?.length) return
    const found = r.positions.find(p => p.symbol === symbol)
    if (found) setSelectedPos(found)
  }, [params, r])

  if (!r) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading...</div>

  const triggered = r.positions.filter(p => p.triggered)
  const protected_ = r.positions.filter(p => p.stop_price != null || p.has_stop)
  const unprotected = r.positions.filter(p => p.stop_price == null && !p.has_stop)
  const stopEntries = Object.entries(r.stops || {})

  // Top 10 positions by daily change %
  const positionsWithChange = r.positions.filter(p => p.day_change_pct != null)
  const top10Change = [...positionsWithChange].sort((a, b) => Math.abs(b.day_change_pct || 0) - Math.abs(a.day_change_pct || 0)).slice(0, 10)

  // RSI distribution
  const rsiOversold = r.positions.filter(p => p.rsi != null && p.rsi < 30).length
  const rsiNeutral = r.positions.filter(p => p.rsi != null && p.rsi >= 30 && p.rsi <= 70).length
  const rsiOverbought = r.positions.filter(p => p.rsi != null && p.rsi > 70).length

  const columns = [
    { key: 'symbol', label: 'Symbol', width: 55, render: (p: Position) => (
      <span style={{ fontWeight: 700, color: p.triggered ? 'var(--red)' : 'var(--text0)' }}>{p.symbol}</span>
    )},
    { key: 'status', label: 'Status', width: 80, render: (p: Position) => (
      <div style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
        <span style={{ fontSize: 8, fontWeight: 700, padding: '2px 8px', borderRadius: 9999, background: p.triggered ? 'rgba(246,70,93,0.15)' : p.stop_price ? 'rgba(14,203,129,0.12)' : 'var(--bg3)', color: p.triggered ? 'var(--red)' : p.stop_price ? 'var(--green)' : 'var(--text3)' }}>
          {p.triggered ? 'TRIGGERED' : p.stop_price ? 'PROTECTED' : 'NONE'}
        </span>
        {p.stop_conf_status && p.stop_conf_status !== 'unknown' && (
          <span style={{ fontSize: 7, fontWeight: 600, padding: '0px 3px', borderRadius: 2,
            background: p.stop_conf_status === 'confirmed' ? 'var(--green-dim)' : p.stop_conf_status === 'intentional_no_stop' ? 'var(--bg3)' : 'var(--amber-dim)',
            color: p.stop_conf_status === 'confirmed' ? 'var(--green)' : p.stop_conf_status === 'intentional_no_stop' ? 'var(--text3)' : 'var(--amber)',
          }}>{p.stop_conf_status === 'confirmed' ? '\u2713' : p.stop_conf_status === 'intentional_no_stop' ? 'EXEMPT' : p.stop_conf_status === 'needs_recommendation' ? 'REC' : '\u26a0'}</span>
        )}
      </div>
    )},
    { key: 'market_value', label: 'Value', width: 65, align: 'right' as const, render: (p: Position) => fmt$(p.market_value) },
    { key: 'current_price', label: 'Price', width: 55, align: 'right' as const, render: (p: Position) => p.current_price > 0 ? fmt$(p.current_price, 2) : <span style={{ color: 'var(--text3)' }} title="Price not available — enrichment may be stale. Run reprice via Actions.">$0</span> },
    { key: 'stop_price', label: 'Stop', width: 55, align: 'right' as const, render: (p: Position) => p.stop_price ? fmt$(p.stop_price, 2) : <span style={{ color: 'var(--text3)' }}>—</span> },
    { key: 'distance_pct', label: 'Dist%', width: 45, align: 'right' as const, render: (p: Position) => p.distance_pct != null ? <span title={`${Math.abs(p.distance_pct).toFixed(1)}% ${p.distance_pct < 0 ? 'below' : 'above'} stop. ${Math.abs(p.distance_pct) < 3 ? 'CLOSE — may trigger soon' : Math.abs(p.distance_pct) < 5 ? 'Approaching — monitor daily' : 'Comfortable distance'}`} style={{ color: deltaColor(-Math.abs(p.distance_pct)) }}>{p.distance_pct.toFixed(1)}%</span> : <span style={{ color: 'var(--text3)' }} title="No stop set — consider adding one via broker">—</span> },
    { key: 'max_loss', label: 'Max Loss', width: 60, align: 'right' as const, sortKey: (p: Position) => p.max_loss, render: (p: Position) => <span style={{ color: 'var(--red)' }}>{fmt$(p.max_loss)}</span> },
  ]

  return (
    <>
      <PageHeader title="Risk Manager" subtitle={`${r.position_count} positions monitored`} />

      {/* Quick nav */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        {[['Daily Brief', '/morning-brief'], ['Approvals', '/approvals'], ['Recovery', '/recovery'], ['Actions', '/actions']].map(([label, route]) => (
          <button key={route} onClick={() => navigate(route)} style={{ fontSize: 10, padding: '5px 12px', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 9999, background: 'rgba(255,255,255,0.04)', color: 'var(--text1)', cursor: 'pointer', fontFamily: 'var(--sans)', transition: 'all 100ms' }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.08)' }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.04)' }}>{label}</button>
        ))}
      </div>

      {triggered.length > 0 && (
        <div style={{ padding: '12px 16px', background: 'rgba(246,70,93,0.08)', border: '1px solid rgba(246,70,93,0.3)', borderRadius: 12, marginBottom: 14, fontSize: 12, color: 'var(--red)', fontWeight: 700, fontFamily: 'var(--sans)', display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 16 }}>🛑</span>
          {triggered.length} STOP{triggered.length !== 1 ? 'S' : ''} TRIGGERED: {triggered.map(t => t.symbol).join(', ')}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 12, marginBottom: 16 }}>
        {[
          { label: 'Stop Risk Heat', value: `${r.portfolio_heat_pct.toFixed(1)}%`, color: r.portfolio_heat_pct > 5 ? 'var(--red)' : r.portfolio_heat_pct > 2 ? 'var(--amber)' : 'var(--green)', sub: r.portfolio_heat_pct > 5 ? 'Elevated — avoid new positions until <3%' : 'Normal range' },
          { label: 'Total Risk $', value: fmt$(r.total_risk_dollars), color: 'var(--red)', sub: 'Sum of max loss if all stops hit' },
          { label: 'Protected', value: `${r.pct_protected.toFixed(0)}%`, sub: `${fmt$(r.total_protected_mv)} with stops`, color: 'var(--green)' },
          { label: 'Unprotected', value: fmt$(r.total_unprotected_mv), color: 'var(--amber)', sub: 'Includes 401k/mutual funds (no stops available)' },
          { label: 'Triggered', value: String(triggered.length), color: triggered.length > 0 ? 'var(--red)' : 'var(--green)', sub: triggered.length > 0 ? 'Verify broker executed' : 'All stops intact' },
        ].map(m => (
          <div key={m.label} style={{ background: 'rgba(16,20,28,0.92)', backdropFilter: 'blur(12px)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 12, padding: '14px 16px' }}>
            <div style={{ fontSize: 9, fontWeight: 600, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: '.05em', marginBottom: 6, fontFamily: 'var(--sans)' }}>{m.label}</div>
            <div style={{ fontSize: 24, fontWeight: 800, color: m.color, fontFamily: 'var(--sans)', lineHeight: 1.1 }}>{m.value}</div>
            {m.sub && <div style={{ fontSize: 10, color: 'var(--text2)', marginTop: 4 }}>{m.sub}</div>}
          </div>
        ))}
      </div>

      {/* Charts Row: Top movers + Protection pie + RSI dist */}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: 12, marginBottom: 16 }}>
        <Card>
          <SectionHeader title="Top 10 Daily Movers" />
          <div style={{ padding: '8px 12px' }}>
            {top10Change.length > 0 ? (
              <BarChartJS
                labels={top10Change.map(p => p.symbol)}
                data={top10Change.map(p => p.day_change_pct || 0)}
                height={140}
              />
            ) : (
              <div style={{ fontSize: 10, color: 'var(--text3)', padding: 12 }}>No intraday change data available.</div>
            )}
          </div>
        </Card>
        <Card>
          <SectionHeader title="Stop Protection" />
          <div style={{ padding: '8px 12px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <div style={{ width: 130, height: 130 }}>
              <DoughnutChart
                labels={['Protected', 'Unprotected']}
                data={[protected_.length, unprotected.length]}
                colors={['#0ecb81', '#f6465d']}
                height={130}
              />
            </div>
            <div style={{ display: 'flex', gap: 12, marginTop: 8, fontSize: 9 }}>
              <span style={{ color: 'var(--green)' }}>{protected_.length} protected</span>
              <span style={{ color: 'var(--red)' }}>{unprotected.length} exposed</span>
            </div>
          </div>
        </Card>
        <Card>
          <SectionHeader title="RSI Distribution" />
          <div style={{ padding: '8px 12px' }}>
            {(rsiOversold + rsiNeutral + rsiOverbought) > 0 ? (
              <>
                <BarChartJS
                  labels={['Oversold <30', 'Neutral 30-70', 'Overbought >70']}
                  data={[rsiOversold, rsiNeutral, rsiOverbought]}
                  colors={['#0ecb81', '#4a90f4', '#f6465d']}
                  height={110}
                />
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, color: 'var(--text3)', marginTop: 4 }}>
                  <span style={{ color: 'var(--green)' }}>{rsiOversold}</span>
                  <span style={{ color: 'var(--accent)' }}>{rsiNeutral}</span>
                  <span style={{ color: 'var(--red)' }}>{rsiOverbought}</span>
                </div>
              </>
            ) : (
              <div style={{ fontSize: 10, color: 'var(--text3)', padding: 12 }}>No RSI data available.</div>
            )}
          </div>
        </Card>
      </div>

      {/* BLOCK 3: Risk escalation lane */}
      {r.escalation && (r.escalation.danger.length > 0 || r.escalation.warning.length > 0 || r.escalation.unprotected.length > 0) && (
        <>
          <SectionHeader title="Escalation Lane" />
          <div style={{ background: 'rgba(16,20,28,0.92)', backdropFilter: 'blur(12px)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 12, padding: '10px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {r.escalation.danger.map((p, i) => (
                <button onClick={() => { const found = r.positions.find(x => x.symbol === p.symbol); if (found) { setSelectedPos(found); setParams(prev => { const q = new URLSearchParams(prev); q.set('symbol', p.symbol); return q }, { replace: true }) } }} key={'d' + i} style={{ display: 'flex', gap: 12, padding: '10px 12px', borderRadius: 10, background: 'rgba(246,70,93,0.06)', border: '1px solid rgba(246,70,93,0.2)', alignItems: 'center', cursor: 'pointer', transition: 'background 100ms' }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(246,70,93,0.12)' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(246,70,93,0.06)' }}>
                  <span style={{ fontSize: 18, fontWeight: 800, color: 'var(--red)', width: 48 }}>{p.symbol}</span>
                  <div style={{ flex: 1 }}><div style={{ fontSize: 11, fontWeight: 600, color: 'var(--red)' }}>Danger · {fmt$(p.max_loss || 0)} at risk</div>
                  <div style={{ fontSize: 9, color: 'var(--text2)' }}>{(p.distance_pct || 0).toFixed(1)}% from stop · {p.account?.replace('schwab_', '')}</div></div>
                </button>
              ))}
              {r.escalation.warning.map((p, i) => (
                <button onClick={() => { const found = r.positions.find(x => x.symbol === p.symbol); if (found) { setSelectedPos(found); setParams(prev => { const q = new URLSearchParams(prev); q.set('symbol', p.symbol); return q }, { replace: true }) } }} key={'w' + i} style={{ display: 'flex', gap: 12, padding: '10px 12px', borderRadius: 10, background: 'rgba(240,185,11,0.05)', border: '1px solid rgba(240,185,11,0.15)', alignItems: 'center', cursor: 'pointer', transition: 'background 100ms' }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(240,185,11,0.1)' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(240,185,11,0.05)' }}>
                  <span style={{ fontSize: 14, fontWeight: 800, color: 'var(--amber)', width: 48 }}>{p.symbol}</span>
                  <div style={{ flex: 1 }}><div style={{ fontSize: 11, fontWeight: 600, color: 'var(--amber)' }}>Warning · {fmt$(p.max_loss || 0)}</div>
                  <div style={{ fontSize: 9, color: 'var(--text2)' }}>{(p.distance_pct || 0).toFixed(1)}% from stop · {p.account?.replace('schwab_', '')}</div></div>
                </button>
              ))}
              {r.escalation.unprotected.map((p, i) => (
                <button onClick={() => navigate(`/portfolio?symbol=${p.symbol}`)} key={'u' + i} style={{ display: 'flex', gap: 12, padding: '8px 12px', borderRadius: 10, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', alignItems: 'center', cursor: 'pointer', transition: 'background 100ms' }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.06)' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.03)' }}>
                  <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text2)', width: 48 }}>{p.symbol}</span>
                  <div style={{ flex: 1 }}><div style={{ fontSize: 11, color: 'var(--text1)' }}>Unprotected · {fmt$(p.market_value || 0)}</div></div>
                </button>
              ))}
              {r.escalation.danger.length === 0 && r.escalation.warning.length === 0 && r.escalation.unprotected.length === 0 && (
                <div style={{ fontSize: 10, color: 'var(--text3)', padding: 8 }}>No escalations in current scope</div>
              )}
            </div>
          </div>
        </>
      )}

      {/* Risk Charts */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 16, marginTop: 16 }}>
        <Card title="Protection Coverage">
          <div style={{ position: 'relative', height: 140 }}>
            <DoughnutChart
              labels={['Protected', 'Unprotected']}
              data={[protected_.length, unprotected.length]}
              colors={['#0ecb81', '#f6465d']}
              height={140}
            />
          </div>
          <div style={{ textAlign: 'center', fontSize: 10, color: 'var(--text3)', marginTop: 6 }}>
            {protected_.length} protected · {unprotected.length} exposed
          </div>
        </Card>
        <Card title="Top Movers Today">
          <BarChartJS
            labels={[...r.positions].sort((a, b) => Math.abs(b.distance_pct || 0) - Math.abs(a.distance_pct || 0)).slice(0, 8).map(p => p.symbol)}
            data={[...r.positions].sort((a, b) => Math.abs(b.distance_pct || 0) - Math.abs(a.distance_pct || 0)).slice(0, 8).map(p => p.distance_pct || 0)}
            height={140}
          />
        </Card>
        <Card title="Stop Distance Distribution">
          <BarChartJS
            labels={['<5%', '5-10%', '10-20%', '>20%', 'None']}
            data={[
              r.positions.filter(p => p.distance_pct != null && p.distance_pct < 5).length,
              r.positions.filter(p => p.distance_pct != null && p.distance_pct >= 5 && p.distance_pct < 10).length,
              r.positions.filter(p => p.distance_pct != null && p.distance_pct >= 10 && p.distance_pct < 20).length,
              r.positions.filter(p => p.distance_pct != null && p.distance_pct >= 20).length,
              r.positions.filter(p => p.distance_pct == null).length,
            ]}
            colors={['#f6465d', '#f0b90b', '#0ecb81', '#4a90f4', '#6b7a8d']}
            height={140}
          />
        </Card>
      </div>

      {/* Position Stop Distance Table */}
      <SectionHeader title="Position Stop Distances" count={r.positions.filter(p => p.stop_price != null).length} />
      <Card>
        <div style={{ maxHeight: 280, overflowY: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10, fontFamily: 'var(--sans)' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <th style={thStyle}>Symbol</th>
                <th style={thStyle}>Value</th>
                <th style={thStyle}>Stop</th>
                <th style={thStyle}>Distance</th>
                <th style={thStyle}>RSI</th>
                <th style={thStyle}>Proximity</th>
              </tr>
            </thead>
            <tbody>
              {[...r.positions].filter(p => p.stop_price != null).sort((a, b) => (a.distance_pct || 99) - (b.distance_pct || 99)).map(p => {
                const dist = p.distance_pct ?? p.distance_to_stop_pct ?? null
                const proxColor = dist == null ? 'var(--text3)' : dist < 3 ? 'var(--red)' : dist < 7 ? 'var(--amber)' : 'var(--green)'
                return (
                  <tr key={p.symbol} style={{ borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer' }}
                    onClick={() => { setSelectedPos(p); setParams(prev => { const q = new URLSearchParams(prev); q.set('symbol', p.symbol); return q }, { replace: true }) }}>
                    <td style={{ ...tdStyle, fontWeight: 700, color: 'var(--accent)' }}>{p.symbol}</td>
                    <td style={{ ...tdStyle, color: 'var(--text1)' }}>{fmt$(p.market_value)}</td>
                    <td style={{ ...tdStyle, color: 'var(--text2)' }}>{p.stop_price ? fmt$(p.stop_price, 2) : '—'}</td>
                    <td style={{ ...tdStyle, color: proxColor, fontWeight: 700 }}>{dist != null ? `${dist.toFixed(1)}%` : '—'}</td>
                    <td style={{ ...tdStyle, color: p.rsi != null ? (p.rsi < 30 ? 'var(--green)' : p.rsi > 70 ? 'var(--red)' : 'var(--text2)') : 'var(--text3)' }}>{p.rsi != null ? p.rsi.toFixed(0) : '—'}</td>
                    <td style={tdStyle}>
                      {dist != null && (
                        <div style={{ width: 60, height: 6, background: 'var(--bg3)', borderRadius: 3, overflow: 'hidden' }}>
                          <div style={{ width: `${Math.min(100, Math.max(5, (1 - dist / 20) * 100))}%`, height: '100%', background: proxColor, borderRadius: 3 }} />
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      <SectionHeader title="Position Risk" count={r.positions.length} />
      <DataGrid columns={columns} data={r.positions} rowKey={p => p.symbol} maxHeight={300}
        onRowClick={p => { setSelectedPos(p); setParams(prev => { const q = new URLSearchParams(prev); q.set('symbol', p.symbol); return q }, { replace: true }) }} />

      {/* Risk detail drawer */}
      <DetailDrawer open={!!selectedPos} onClose={() => setSelectedPos(null)}
        title={selectedPos?.symbol || ''} subtitle={`Risk Detail | ${selectedPos?.status || ''}`}>
        {selectedPos && (
          <>
            <DrawerSection title="Position">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                <DrawerStat label="Current Price" value={fmt$(selectedPos.current_price, 2)} />
                <DrawerStat label="Stop Price" value={selectedPos.stop_price != null ? fmt$(selectedPos.stop_price, 2) : '—'} />
                <DrawerStat label="Market Value" value={fmt$(selectedPos.market_value)} />
                <DrawerStat label="Max Loss" value={fmt$(selectedPos.max_loss)} color="var(--red)" />
                <DrawerStat label="Distance %" value={selectedPos.distance_pct != null ? selectedPos.distance_pct.toFixed(1) + '%' : '—'} color={selectedPos.distance_pct != null ? (selectedPos.distance_pct > 10 ? 'var(--green)' : selectedPos.distance_pct > 5 ? 'var(--amber)' : 'var(--red)') : undefined} />
                <DrawerStat label="Triggered" value={selectedPos.triggered ? 'YES' : 'No'} color={selectedPos.triggered ? 'var(--red)' : 'var(--green)'} />
                {selectedPos.rsi != null && <DrawerStat label="RSI" value={selectedPos.rsi.toFixed(0)} color={selectedPos.rsi < 30 ? 'var(--green)' : selectedPos.rsi > 70 ? 'var(--red)' : 'var(--text1)'} />}
                {selectedPos.day_change_pct != null && <DrawerStat label="Day Change" value={`${selectedPos.day_change_pct.toFixed(2)}%`} color={selectedPos.day_change_pct >= 0 ? 'var(--green)' : 'var(--red)'} />}
              </div>
            </DrawerSection>
            {selectedPos.stop_conf_status && (
              <DrawerSection title="Stop Confirmation">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                  <DrawerStat label="Status" value={selectedPos.stop_conf_status.replace(/_/g, ' ')} color={selectedPos.stop_confirmed ? 'var(--green)' : 'var(--amber)'} />
                  {selectedPos.stop_price_confirmed != null && <DrawerStat label="Confirmed Price" value={fmt$(selectedPos.stop_price_confirmed, 2)} color="var(--green)" />}
                  {selectedPos.stop_confirmed_at && <DrawerStat label="Confirmed At" value={selectedPos.stop_confirmed_at} />}
                  {(selectedPos.reminder_count ?? 0) > 0 && <DrawerStat label="Reminders Sent" value={String(selectedPos.reminder_count)} color={(selectedPos.reminder_count ?? 0) > 2 ? 'var(--red)' : 'var(--amber)'} />}
                </div>
              </DrawerSection>
            )}
            {selectedPos.distance_pct != null && (
              <DrawerSection title="Distance to Stop">
                <div style={{ height: 10, background: 'var(--bg3)', borderRadius: 4, overflow: 'hidden', marginTop: 4 }}>
                  <div style={{ width: `${Math.min(Math.max(selectedPos.distance_pct * 5, 4), 100)}%`, height: '100%', borderRadius: 4, background: selectedPos.distance_pct > 10 ? 'var(--green)' : selectedPos.distance_pct > 5 ? 'var(--amber)' : 'var(--red)' }} />
                </div>
              </DrawerSection>
            )}
            <DrawerSection title="Links & Drillthrough">
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <button onClick={() => navigate(`/portfolio?symbol=${selectedPos.symbol}`)} style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer' }}>Open Holdings</button>
                <button onClick={() => navigate(`/research?symbol=${selectedPos.symbol}`)} style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--bg3)', color: 'var(--text1)', cursor: 'pointer' }}>Open Research</button>
                <a href={`https://finviz.com/quote.ashx?t=${selectedPos.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Finviz</a>
                <a href={`https://finance.yahoo.com/quote/${selectedPos.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Yahoo</a>
              </div>
            </DrawerSection>
            <div style={{ marginTop: 14, padding: '8px 12px', background: 'rgba(255,255,255,0.03)', borderRadius: 8, fontSize: 9, color: 'var(--text3)' }}>
              Stops require broker action. Review analysis in Recovery Watch or check Approvals for pending items.
            </div>
          </>
        )}
      </DetailDrawer>

      <SectionHeader title="Stop Configuration" count={stopEntries.length} />
      <Card compact>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 6 }}>
          {stopEntries.map(([sym, s]) => (
            <div key={sym} style={{ padding: '4px 8px', background: s.triggered ? 'var(--red-dim)' : 'var(--bg3)', borderRadius: 'var(--radius)', border: `1px solid ${s.triggered ? 'var(--red)' : 'var(--border-subtle)'}` }}>
              <span style={{ fontWeight: 700, fontSize: 11 }}>{sym}</span>
              <span style={{ float: 'right', fontSize: 10, color: s.stop_price ? 'var(--text1)' : 'var(--text3)' }}>{s.stop_price ? fmt$(s.stop_price, 2) : '—'}</span>
              {s.triggered && <div style={{ fontSize: 8, color: 'var(--red)', fontWeight: 700, marginTop: 2 }}>TRIGGERED</div>}
            </div>
          ))}
        </div>
      </Card>
    </>
  )
}

const thStyle: React.CSSProperties = { textAlign: 'left', padding: '6px 8px', color: 'var(--text3)', fontWeight: 600, fontSize: 9, textTransform: 'uppercase', letterSpacing: '.04em' }
const tdStyle: React.CSSProperties = { padding: '6px 8px', color: 'var(--text1)' }
