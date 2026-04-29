import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import SectionHeader from '../components/SectionHeader'
import MetricTile from '../components/MetricTile'
import DetailDrawer, { DrawerStat, DrawerSection } from '../components/DetailDrawer'
import DataGrid from '../components/DataGrid'
import { useApi } from '../hooks/useApi'
import { fmt$, fmtPct, deltaColor } from '../lib/format'

interface Position { symbol: string; market_value: number; stop_price: number | null; current_price: number; distance_pct: number | null; max_loss: number; status: string; triggered: boolean }
interface EscItem { symbol: string; max_loss?: number; distance_pct?: number; market_value?: number; account?: string }
interface RiskData { portfolio_heat_pct: number; total_risk_dollars: number; pct_protected: number; total_protected_mv: number; total_unprotected_mv: number; position_count: number; positions: Position[]; stops: Record<string, { stop_price: number | null; triggered: boolean }>; escalation?: { danger: EscItem[]; warning: EscItem[]; unprotected: EscItem[] } }

export default function Risk() {
  const { data: r } = useApi<RiskData>('/api/v2/risk')
  const [selectedPos, setSelectedPos] = useState<Position | null>(null)
  if (!r) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading...</div>

  const triggered = r.positions.filter(p => p.triggered)
  const protected_ = r.positions.filter(p => p.stop_price != null)
  const unprotected = r.positions.filter(p => p.stop_price == null)
  const stopEntries = Object.entries(r.stops)

  const columns = [
    { key: 'symbol', label: 'Symbol', width: 55, render: (p: Position) => (
      <span style={{ fontWeight: 700, color: p.triggered ? 'var(--red)' : 'var(--text0)' }}>{p.symbol}</span>
    )},
    { key: 'status', label: 'Status', width: 65, render: (p: Position) => (
      <span style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 3, background: p.triggered ? 'var(--red-dim)' : p.stop_price ? 'var(--green-dim)' : 'var(--bg3)', color: p.triggered ? 'var(--red)' : p.stop_price ? 'var(--green)' : 'var(--text3)' }}>
        {p.triggered ? 'TRIGGERED' : p.stop_price ? 'PROTECTED' : 'NONE'}
      </span>
    )},
    { key: 'market_value', label: 'Value', width: 65, align: 'right' as const, render: (p: Position) => fmt$(p.market_value) },
    { key: 'current_price', label: 'Price', width: 55, align: 'right' as const, render: (p: Position) => fmt$(p.current_price, 2) },
    { key: 'stop_price', label: 'Stop', width: 55, align: 'right' as const, render: (p: Position) => p.stop_price ? fmt$(p.stop_price, 2) : <span style={{ color: 'var(--text3)' }}>—</span> },
    { key: 'distance_pct', label: 'Dist%', width: 45, align: 'right' as const, render: (p: Position) => p.distance_pct != null ? <span style={{ color: deltaColor(-Math.abs(p.distance_pct)) }}>{p.distance_pct.toFixed(1)}%</span> : <span style={{ color: 'var(--text3)' }}>—</span> },
    { key: 'max_loss', label: 'Max Loss', width: 60, align: 'right' as const, sortKey: (p: Position) => p.max_loss, render: (p: Position) => <span style={{ color: 'var(--red)' }}>{fmt$(p.max_loss)}</span> },
  ]

  return (
    <>
      <PageHeader title="Risk Manager" subtitle={`${r.position_count} positions monitored`} />

      {triggered.length > 0 && (
        <div style={{ padding: '8px 12px', background: 'var(--red-dim)', border: '1px solid var(--red)', borderRadius: 'var(--radius-md)', marginBottom: 12, fontSize: 11, color: 'var(--red)', fontWeight: 600 }}>
          {triggered.length} STOP(S) TRIGGERED: {triggered.map(t => t.symbol).join(', ')}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <MetricTile label="Portfolio Heat" value={`${r.portfolio_heat_pct.toFixed(1)}%`} deltaColor={r.portfolio_heat_pct > 5 ? 'var(--red)' : r.portfolio_heat_pct > 2 ? 'var(--amber)' : 'var(--green)'} />
        <MetricTile label="Total Risk" value={fmt$(r.total_risk_dollars)} deltaColor="var(--red)" />
        <MetricTile label="Protected" value={`${r.pct_protected.toFixed(0)}%`} delta={fmt$(r.total_protected_mv)} deltaColor="var(--green)" />
        <MetricTile label="Unprotected" value={fmt$(r.total_unprotected_mv)} deltaColor="var(--amber)" />
        <MetricTile label="Triggered" value={String(triggered.length)} deltaColor={triggered.length > 0 ? 'var(--red)' : 'var(--green)'} />
      </div>

      {/* BLOCK 3: Risk escalation lane */}
      {r.escalation && (r.escalation.danger.length > 0 || r.escalation.warning.length > 0 || r.escalation.unprotected.length > 0) && (
        <>
          <SectionHeader title="Escalation Lane" />
          <Card compact>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
              {r.escalation.danger.map((p, i) => (
                <div key={'d' + i} style={{ display: 'flex', gap: 8, padding: '5px 8px', borderRadius: 'var(--radius)', background: 'var(--red-dim)', borderLeft: '3px solid var(--red)', alignItems: 'center' }}>
                  <span style={{ fontSize: 13 }}>{'\u{1f6d1}'}</span>
                  <div><div style={{ fontSize: 11, fontWeight: 600, color: 'var(--red)' }}>{p.symbol} · {fmt$(p.max_loss || 0)}</div>
                  <div style={{ fontSize: 9, color: 'var(--text2)' }}>{(p.distance_pct || 0).toFixed(1)}% from stop · {p.account?.replace('schwab_', '')}</div></div>
                </div>
              ))}
              {r.escalation.warning.map((p, i) => (
                <div key={'w' + i} style={{ display: 'flex', gap: 8, padding: '5px 8px', borderRadius: 'var(--radius)', background: 'var(--amber-dim)', borderLeft: '3px solid var(--amber)', alignItems: 'center' }}>
                  <span style={{ fontSize: 13 }}>{'\u26a0\ufe0f'}</span>
                  <div><div style={{ fontSize: 11, fontWeight: 600, color: 'var(--amber)' }}>{p.symbol} · {fmt$(p.max_loss || 0)}</div>
                  <div style={{ fontSize: 9, color: 'var(--text2)' }}>{(p.distance_pct || 0).toFixed(1)}% from stop · {p.account?.replace('schwab_', '')}</div></div>
                </div>
              ))}
              {r.escalation.unprotected.map((p, i) => (
                <div key={'u' + i} style={{ display: 'flex', gap: 8, padding: '5px 8px', borderRadius: 'var(--radius)', background: 'var(--bg3)', borderLeft: '3px solid var(--text3)', alignItems: 'center' }}>
                  <span style={{ fontSize: 13 }}>{'\u{1f9e9}'}</span>
                  <div><div style={{ fontSize: 11, color: 'var(--text1)' }}>{p.symbol} unprotected</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>{fmt$(p.market_value || 0)} market value</div></div>
                </div>
              ))}
              {r.escalation.danger.length === 0 && r.escalation.warning.length === 0 && r.escalation.unprotected.length === 0 && (
                <div style={{ fontSize: 10, color: 'var(--text3)', padding: 8 }}>No escalations in current scope</div>
              )}
            </div>
          </Card>
        </>
      )}

      <SectionHeader title="Position Risk" count={r.positions.length} />
      <DataGrid columns={columns} data={r.positions} rowKey={p => p.symbol} maxHeight={300}
        onRowClick={p => setSelectedPos(p)} />

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
              </div>
            </DrawerSection>
            {selectedPos.distance_pct != null && (
              <DrawerSection title="Distance to Stop">
                <div style={{ height: 10, background: 'var(--bg3)', borderRadius: 4, overflow: 'hidden', marginTop: 4 }}>
                  <div style={{ width: `${Math.min(Math.max(selectedPos.distance_pct * 5, 4), 100)}%`, height: '100%', borderRadius: 4, background: selectedPos.distance_pct > 10 ? 'var(--green)' : selectedPos.distance_pct > 5 ? 'var(--amber)' : 'var(--red)' }} />
                </div>
              </DrawerSection>
            )}
            <DrawerSection title="Links">
              <div style={{ display: 'flex', gap: 6 }}>
                <a href={`https://finviz.com/quote.ashx?t=${selectedPos.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Finviz</a>
                <a href={`https://finance.yahoo.com/quote/${selectedPos.symbol}`} target="_blank" rel="noreferrer" style={{ fontSize: 10, padding: '4px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius)', color: 'var(--accent)', textDecoration: 'none' }}>Yahoo</a>
              </div>
            </DrawerSection>
            <div style={{ marginTop: 14, padding: '6px 10px', background: 'var(--bg3)', borderRadius: 'var(--radius)', fontSize: 9, color: 'var(--text3)' }}>
              Read-only view. Stop editing and trail % configuration deferred.
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
