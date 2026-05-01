import { useState, useEffect, useMemo } from 'react'

type SortDir = 'asc' | 'desc'

export default function PortfolioIntelligence() {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [sortCol, setSortCol] = useState('market_value')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [filterAccount, setFilterAccount] = useState('all')
  const [filterType, setFilterType] = useState('all')
  const [search, setSearch] = useState('')
  const [expandedSector, setExpandedSector] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    fetch('/api/v2/portfolio-intelligence')
      .then(r => r.json())
      .then(d => { if (d.ok) setData(d.data); else setError(d.error || 'Failed') })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))
  }, [])

  const filtered = useMemo(() => {
    if (!data) return []
    let p = data.positions as any[]
    if (filterAccount !== 'all') p = p.filter((x: any) => x.account === filterAccount)
    if (filterType !== 'all') p = p.filter((x: any) => (x.security_type || '').toLowerCase().includes(filterType.toLowerCase()))
    if (search) {
      const q = search.toLowerCase()
      p = p.filter((x: any) => x.symbol?.toLowerCase().includes(q) || x.name?.toLowerCase().includes(q) || x.sector?.toLowerCase().includes(q))
    }
    return [...p].sort((a: any, b: any) => {
      const va = a[sortCol], vb = b[sortCol]
      if (typeof va === 'string' && typeof vb === 'string')
        return sortDir === 'desc' ? vb.localeCompare(va) : va.localeCompare(vb)
      return sortDir === 'desc' ? Number(vb || 0) - Number(va || 0) : Number(va || 0) - Number(vb || 0)
    })
  }, [data, sortCol, sortDir, filterAccount, filterType, search])

  const pctColor = (v: number) => v > 10 ? '#00ff88' : v > 0 ? '#4ade80' : v === 0 ? '#3a5a80' : v > -10 ? '#ff4466' : '#ff0033'

  if (loading) return <div style={{ padding: 40, color: '#5a7fa8', textAlign: 'center' }}>Loading portfolio intelligence...</div>
  if (error) return <div style={{ padding: 40, color: '#ff4466' }}>Error: {error}</div>
  if (!data) return null

  const tv = data.total_value || 1
  const cl = data.classification || {}
  const crossSyms = (data.cross_account_symbols || []) as any[]

  return (
    <div style={{ padding: 24, color: '#c8daf5', fontFamily: 'system-ui, sans-serif', maxWidth: 1200, margin: '0 auto' }}>
      {/* Header */}
      <h1 style={{ fontSize: 22, fontWeight: 700, color: '#fff', marginBottom: 4 }}>Portfolio Intelligence</h1>
      <div style={{ fontSize: 13, color: '#5a7fa8', marginBottom: 20 }}>
        {data.total_positions} positions &middot; 4 accounts &middot; ${tv.toLocaleString(undefined, { maximumFractionDigits: 0 })} &middot; {cl.classified_pct}% classified
      </div>

      {/* Account tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 10, marginBottom: 20 }}>
        {(data.accounts || []).map((a: any) => (
          <Card key={a.account}>
            <div style={{ fontSize: 9, color: '#5a7fa8', fontFamily: 'var(--mono)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>{a.account.replace(/_/g, ' ')}</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: '#fff', marginBottom: 2 }}>${(a.total_value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
            <div style={{ fontSize: 11, color: '#5a7fa8' }}>{a.position_count} positions</div>
            {a.account?.includes('401k') && a.total_cost === 0
              ? <div style={{ fontSize: 11, color: '#3a5a80', marginTop: 4 }}>P&L N/A — no cost basis</div>
              : a.unrealized_pct !== 0 && <div style={{ fontSize: 13, fontWeight: 600, color: pctColor(a.unrealized_pct), marginTop: 4 }}>{a.unrealized_pct > 0 ? '+' : ''}{a.unrealized_pct?.toFixed(1)}%</div>}
          </Card>
        ))}
        <Card>
          <div style={{ fontSize: 9, color: '#5a7fa8', fontFamily: 'var(--mono)', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>Classification</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: cl.classified_pct >= 80 ? '#00ff88' : '#ffaa00' }}>{cl.classified_pct}%</div>
          <div style={{ fontSize: 11, color: '#5a7fa8' }}>{cl.classified}/{cl.total} classified</div>
          {cl.unclassified > 0 && <div style={{ fontSize: 11, color: '#ffaa00', marginTop: 4 }}>{cl.unclassified} unknown</div>}
        </Card>
      </div>

      {/* Sector breakdown */}
      <Card>
        <SH>Sector Breakdown</SH>
        {(data.sectors || []).map((s: any) => {
          const expanded = expandedSector === s.sector
          const unc = s.sector.includes('Unclassified') || s.sector === 'Cash'
          return (
            <div key={s.sector}>
              <div onClick={() => setExpandedSector(expanded ? null : s.sector)} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0', cursor: 'pointer', borderBottom: '1px solid #0f1520' }}>
                <div style={{ minWidth: 180, fontSize: 13, color: unc ? '#ffaa00' : '#c8daf5' }}>{s.sector}</div>
                <div style={{ flex: 1, height: 8, background: '#1e3050', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${Math.min(s.weight_pct * 2, 100)}%`, background: unc ? '#ffaa00' : s.unrealized_pct >= 0 ? '#00ff88' : '#ff4466', borderRadius: 4, transition: 'width .3s' }} />
                </div>
                <div style={{ minWidth: 90, textAlign: 'right', fontSize: 13, color: '#c8daf5' }}>${(s.total_value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
                <div style={{ minWidth: 50, textAlign: 'right', fontSize: 12, color: '#5a7fa8' }}>{s.weight_pct?.toFixed(1)}%</div>
                <div style={{ minWidth: 65, textAlign: 'right', fontSize: 12, fontWeight: 600, color: s.unrealized_pct === 0 ? '#5a7fa8' : pctColor(s.unrealized_pct) }}>
                  {s.unrealized_pct !== 0 ? `${s.unrealized_pct > 0 ? '+' : ''}${s.unrealized_pct?.toFixed(1)}%` : 'N/A'}
                </div>
                <div style={{ fontSize: 11, color: '#3a5a80', minWidth: 20 }}>{expanded ? '\u25B2' : '\u25BC'}</div>
              </div>
              {expanded && (
                <div style={{ background: '#0a0e18', padding: 12, borderRadius: 4, marginBottom: 4 }}>
                  {(data.positions || []).filter((p: any) => p.sector === s.sector).map((p: any) => (
                    <div key={p.symbol + p.account} style={{ display: 'flex', gap: 12, padding: '4px 0', fontSize: 12, borderBottom: '1px solid #1e3050' }}>
                      <span style={{ minWidth: 60, color: '#c8daf5', fontFamily: 'var(--mono)', fontWeight: 700 }}>{p.symbol}</span>
                      <span style={{ flex: 1, color: '#5a7fa8' }}>{p.name}</span>
                      <span style={{ color: '#5a7fa8', minWidth: 120 }}>{p.account.replace(/_/g, ' ')}</span>
                      <span style={{ minWidth: 80, textAlign: 'right', color: '#c8daf5' }}>${(p.market_value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                      <span style={{ minWidth: 65, textAlign: 'right', color: pctColor(p.unrealized_pct), fontWeight: 600 }}>{p.unrealized_pct !== 0 ? `${p.unrealized_pct > 0 ? '+' : ''}${p.unrealized_pct?.toFixed(1)}%` : '\u2014'}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </Card>

      {/* Cross-account */}
      {crossSyms.length > 0 && (
        <Card>
          <SH>Symbols Held Across Multiple Accounts ({crossSyms.length})</SH>
          {crossSyms.map((cs: any) => (
            <div key={cs.symbol} style={{ marginBottom: 16, paddingBottom: 16, borderBottom: '1px solid #1e3050' }}>
              <div style={{ display: 'flex', gap: 12, alignItems: 'baseline', marginBottom: 8 }}>
                <span style={{ fontSize: 15, fontWeight: 700, color: '#fff', fontFamily: 'var(--mono)' }}>{cs.symbol}</span>
                <span style={{ fontSize: 12, color: '#5a7fa8' }}>{cs.name}</span>
                <span style={{ marginLeft: 'auto', fontSize: 11, color: '#00d4ff', background: 'rgba(0,212,255,.1)', border: '1px solid rgba(0,212,255,.3)', borderRadius: 4, padding: '2px 8px' }}>{cs.accounts.length} accounts</span>
                <span style={{ fontSize: 13, color: '#c8daf5' }}>${(cs.total_value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })} total</span>
              </div>
              {(cs.accounts || []).map((a: any) => (
                <div key={a.account} style={{ display: 'flex', gap: 12, padding: '4px 0 4px 16px', fontSize: 12 }}>
                  <span style={{ color: '#5a7fa8', minWidth: 160 }}>{'\u2514'} {a.account.replace(/_/g, ' ')}</span>
                  <span style={{ color: '#c8daf5', minWidth: 80 }}>${(a.market_value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                  <span style={{ color: '#5a7fa8', minWidth: 60 }}>{a.weight_in_account?.toFixed(1)}%</span>
                  <span style={{ color: pctColor(a.unrealized_pct), fontWeight: 600 }}>{a.unrealized_pct !== 0 ? `${a.unrealized_pct > 0 ? '+' : ''}${a.unrealized_pct?.toFixed(1)}%` : '\u2014'}</span>
                </div>
              ))}
            </div>
          ))}
        </Card>
      )}

      {/* Performance rankings */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16 }}>
        <Card>
          <SH>Best Performers</SH>
          {(data.best_performers || []).map((p: any, i: number) => (
            <div key={p.symbol + p.account} style={{ display: 'flex', gap: 8, padding: '6px 0', borderBottom: '1px solid #0f1520', alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: '#3a5a80', minWidth: 16 }}>{i + 1}</span>
              <span style={{ fontFamily: 'var(--mono)', fontWeight: 700, color: '#c8daf5', minWidth: 55 }}>{p.symbol}</span>
              <span style={{ flex: 1, fontSize: 11, color: '#5a7fa8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.sector}</span>
              <span style={{ fontSize: 13, fontWeight: 700, color: pctColor(p.unrealized_pct), minWidth: 60, textAlign: 'right' }}>+{p.unrealized_pct?.toFixed(1)}%</span>
              <span style={{ fontSize: 11, color: '#5a7fa8', minWidth: 70, textAlign: 'right' }}>${(p.market_value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
            </div>
          ))}
        </Card>
        <Card>
          <SH>Worst Performers</SH>
          {(data.worst_performers || []).map((p: any, i: number) => (
            <div key={p.symbol + p.account} style={{ display: 'flex', gap: 8, padding: '6px 0', borderBottom: '1px solid #0f1520', alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: '#3a5a80', minWidth: 16 }}>{i + 1}</span>
              <span style={{ fontFamily: 'var(--mono)', fontWeight: 700, color: '#c8daf5', minWidth: 55 }}>{p.symbol}</span>
              <span style={{ flex: 1, fontSize: 11, color: '#5a7fa8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.sector}</span>
              <span style={{ fontSize: 13, fontWeight: 700, color: pctColor(p.unrealized_pct), minWidth: 60, textAlign: 'right' }}>{p.unrealized_pct?.toFixed(1)}%</span>
              <span style={{ fontSize: 11, color: '#5a7fa8', minWidth: 70, textAlign: 'right' }}>${(p.market_value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
            </div>
          ))}
        </Card>
      </div>

      {/* Full position table */}
      <Card>
        <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap', alignItems: 'center' }}>
          <SH>All Positions ({filtered.length})</SH>
          <input placeholder="Search..." value={search} onChange={e => setSearch(e.target.value)}
            style={{ background: '#0a0e18', border: '1px solid #253860', borderRadius: 6, padding: '6px 12px', color: '#c8daf5', fontSize: 12, width: 200, outline: 'none', marginLeft: 'auto' }} />
          <div style={{ display: 'flex', gap: 4 }}>
            {['all', 'fidelity_401k', 'schwab_rollover_ira', 'schwab_taxable', 'schwab_roth'].map(a => (
              <Btn key={a} active={filterAccount === a} onClick={() => setFilterAccount(a)}>{a === 'all' ? 'All' : a.replace('schwab_', '').replace('fidelity_', '').replace(/_/g, ' ')}</Btn>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 4 }}>
            {['all', 'Stock', 'ETF', 'Mutual Fund'].map(t => (
              <Btn key={t} active={filterType === t} onClick={() => setFilterType(t)} accent>{t}</Btn>
            ))}
          </div>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid #1e3050' }}>
                {[['symbol', 'Symbol'], ['name', 'Name'], ['security_type', 'Type'], ['sector', 'Sector'], ['account', 'Account'], ['market_value', 'Value'], ['unrealized_pct', 'P&L %'], ['weight_pct', 'Weight']].map(([col, label]) => (
                  <th key={col} onClick={() => { if (sortCol === col) setSortDir(d => d === 'desc' ? 'asc' : 'desc'); else { setSortCol(col); setSortDir('desc') } }}
                    style={{ padding: '8px 6px', textAlign: col === 'symbol' || col === 'name' || col === 'sector' || col === 'account' || col === 'security_type' ? 'left' : 'right', color: sortCol === col ? '#00d4ff' : '#5a7fa8', fontWeight: sortCol === col ? 700 : 400, cursor: 'pointer', whiteSpace: 'nowrap', fontFamily: 'var(--mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 1 }}>
                    {label}{sortCol === col ? (sortDir === 'desc' ? ' \u25BC' : ' \u25B2') : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((p: any, i: number) => {
                const unc = p.sector?.includes('Unclassified')
                const multi = crossSyms.some((cs: any) => cs.symbol === p.symbol)
                return (
                  <tr key={p.symbol + p.account + i} style={{ borderBottom: '1px solid #0f1520', background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)' }}>
                    <td style={{ padding: '7px 6px', fontFamily: 'var(--mono)', fontWeight: 700, color: '#c8daf5', whiteSpace: 'nowrap' }}>{p.symbol}{multi && <span style={{ marginLeft: 4, color: '#00d4ff', fontSize: 10 }}>{'\u2295'}</span>}</td>
                    <td style={{ padding: '7px 6px', color: '#7a9cc8', maxWidth: 130, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name}</td>
                    <td style={{ padding: '7px 6px', color: '#5a7fa8', fontSize: 11 }}>{p.security_type}</td>
                    <td style={{ padding: '7px 6px', color: unc ? '#ffaa00' : '#7a9cc8', whiteSpace: 'nowrap', fontSize: 11 }}>{unc ? '\u26A0 ' : ''}{p.sector}</td>
                    <td style={{ padding: '7px 6px', color: '#5a7fa8', fontSize: 11, whiteSpace: 'nowrap' }}>{p.account?.replace(/_/g, ' ')}</td>
                    <td style={{ padding: '7px 6px', color: '#c8daf5', textAlign: 'right', fontWeight: 600 }}>${(p.market_value || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}</td>
                    <td style={{ padding: '7px 6px', textAlign: 'right', fontWeight: 700, fontSize: 13, color: p.account?.includes('401k') && p.cost_basis === 0 ? '#3a5a80' : pctColor(p.unrealized_pct) }}>
                      {p.account?.includes('401k') && p.cost_basis === 0
                        ? <span style={{ fontWeight: 400, fontSize: 11 }}>N/A (401k)</span>
                        : p.unrealized_pct > 1000
                          ? <span title="Very old position — verify cost basis is complete">{`+${p.unrealized_pct?.toFixed(1)}%`} <span style={{ fontSize: 9, cursor: 'help' }}>{'\u26A0'}</span></span>
                          : p.unrealized_pct !== 0 ? `${p.unrealized_pct > 0 ? '+' : ''}${p.unrealized_pct?.toFixed(1)}%` : '\u2014'}
                    </td>
                    <td style={{ padding: '7px 6px', textAlign: 'right', color: '#5a7fa8' }}>{p.weight_pct?.toFixed(1)}%</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}

function Card({ children }: { children: React.ReactNode }) {
  return <div style={{ background: '#0f1520', border: '1px solid #1e3050', borderRadius: 10, padding: 16, marginBottom: 16 }}>{children}</div>
}
function SH({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 11, fontFamily: 'var(--mono)', textTransform: 'uppercase', letterSpacing: 2, color: '#5a7fa8', marginBottom: 12 }}>{children}</div>
}
function Btn({ children, active, onClick, accent }: { children: React.ReactNode; active: boolean; onClick: () => void; accent?: boolean }) {
  const c = accent ? '#aa55ff' : '#00d4ff'
  return <button onClick={onClick} style={{ padding: '4px 10px', borderRadius: 4, fontSize: 10, cursor: 'pointer', background: active ? `${c}18` : 'transparent', border: `1px solid ${active ? `${c}60` : '#1e3050'}`, color: active ? c : '#5a7fa8', textTransform: 'capitalize' }}>{children}</button>
}
