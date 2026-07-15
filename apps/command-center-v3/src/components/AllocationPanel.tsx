import { useMemo, useState } from 'react'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'
import { fmt$ } from '../lib/format'
import RiskHeatmapGrid from './risk/RiskHeatmapGrid'

const COLORS = ['#60a5fa', '#22c55e', '#f59e0b', '#a855f7', '#ef4444', '#06b6d4', '#e879f9', '#fb923c', '#34d399', '#f472b6']

type SectorRow = { name: string; value: number; pct?: number }

interface Props {
  sectors: SectorRow[]
  sectorsByAccount?: Record<string, SectorRow[]>
  holdings: any[]
  acctColor: (a: string) => string
  onOpenHolding?: (symbol: string, account: string) => void
  onGoHoldings?: () => void
}

function acctLabel(a: string) {
  return (a || 'unknown').replace(/_/g, ' ')
}

/**
 * Dedicated Allocation page: sector mix + where each sector lives by account,
 * plus top holdings per sector. Keeps Holdings free of the donut sidebar.
 */
export default function AllocationPanel({
  sectors, sectorsByAccount = {}, holdings, acctColor, onOpenHolding, onGoHoldings,
}: Props) {
  const [selectedSector, setSelectedSector] = useState<string | null>(null)
  const total = useMemo(() => sectors.reduce((s, x) => s + (Number(x.value) || 0), 0), [sectors])
  const accounts = useMemo(() => Object.keys(sectorsByAccount).sort(), [sectorsByAccount])

  // sector → account → $ from live holdings (ground truth for "where is it")
  const { bySectorAcct, sectorHoldings } = useMemo(() => {
    const by: Record<string, Record<string, number>> = {}
    const sh: Record<string, { symbol: string; account: string; value: number; shares: number }[]> = {}
    for (const h of holdings || []) {
      if (h?.is_cash) continue
      const sector = String(h.sector || 'Other / Unclassified')
      const acct = String(h.account || 'unknown')
      const val = Number(h.market_value) || 0
      by[sector] ??= {}
      by[sector][acct] = (by[sector][acct] || 0) + val
      sh[sector] ??= []
      sh[sector].push({
        symbol: String(h.symbol || '').toUpperCase(),
        account: acct,
        value: val,
        shares: Number(h.shares) || 0,
      })
    }
    for (const k of Object.keys(sh)) {
      sh[k].sort((a, b) => b.value - a.value)
    }
    return { bySectorAcct: by, sectorHoldings: sh }
  }, [holdings])

  // account totals for the account strip
  const accountTotals = useMemo(() => {
    const m: Record<string, number> = {}
    for (const h of holdings || []) {
      const a = String(h.account || 'unknown')
      m[a] = (m[a] || 0) + (Number(h.market_value) || 0)
    }
    return Object.entries(m).sort((a, b) => b[1] - a[1])
  }, [holdings])

  const activeSector = selectedSector || sectors[0]?.name || null
  const activeHoldings = activeSector ? (sectorHoldings[activeSector] || []) : []
  const activeAcctMix = activeSector ? (bySectorAcct[activeSector] || {}) : {}
  const activeAcctRows = Object.entries(activeAcctMix).sort((a, b) => b[1] - a[1])
  const activeTotal = activeAcctRows.reduce((s, [, v]) => s + v, 0)

  if (!sectors.length && !holdings.length) {
    return (
      <div style={{ padding: 24, color: 'var(--text3)', fontSize: 12, textAlign: 'center', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }}>
        No allocation data yet. Sync holdings or wait for overview sectors.
      </div>
    )
  }

  return (
    <div data-testid="allocation-panel" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{
        display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap',
        padding: '12px 14px', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10,
        borderLeft: '4px solid #60a5fa',
      }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 800, color: 'var(--text0)' }}>Portfolio allocation</div>
          <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 3, lineHeight: 1.45 }}>
            Sector mix and <b style={{ color: 'var(--text1)' }}>where each dollar sits</b> (account breakdown).
            Click a sector to see holdings and accounts. Total invested · {fmt$(total, 0)}.
          </div>
        </div>
        {onGoHoldings && (
          <button
            type="button"
            data-testid="allocation-go-holdings"
            onClick={onGoHoldings}
            style={{
              fontSize: 11, fontWeight: 700, padding: '7px 12px', borderRadius: 6, cursor: 'pointer',
              border: '1px solid #60a5fa55', background: 'rgba(96,165,250,.12)', color: '#60a5fa',
            }}
          >
            Open Holdings →
          </button>
        )}
      </div>

      {/* Account strip — where capital lives */}
      <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 14px' }}>
        <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text2)', textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 10 }}>
          Capital by account
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 8 }}>
          {accountTotals.map(([a, v]) => {
            const pct = total > 0 ? (v / total) * 100 : 0
            return (
              <div key={a} style={{
                padding: '10px 12px', borderRadius: 8, background: 'var(--bg2)',
                border: `1px solid ${acctColor(a)}44`,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: acctColor(a) }} />
                  <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--text0)' }}>{acctLabel(a)}</span>
                </div>
                <div style={{ fontFamily: 'monospace', fontSize: 14, fontWeight: 800, color: 'var(--text0)' }}>{fmt$(v, 0)}</div>
                <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>{pct.toFixed(1)}% of portfolio</div>
                <div style={{ marginTop: 6, height: 4, borderRadius: 2, background: 'var(--bg0)', overflow: 'hidden' }}>
                  <div style={{ width: `${Math.min(100, pct)}%`, height: '100%', background: acctColor(a), borderRadius: 2 }} />
                </div>
              </div>
            )
          })}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, 320px) 1fr', gap: 14 }}>
        {/* Donut + sector list */}
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
          <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)', marginBottom: 8 }}>Sector mix</div>
          {sectors.length === 0 ? (
            <div style={{ color: 'var(--text3)', fontSize: 11 }}>No sector data from overview</div>
          ) : (
            <ResponsiveContainer width="100%" height={210}>
              <PieChart>
                <Pie
                  data={sectors}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={82}
                  stroke="var(--bg0)"
                  strokeWidth={2}
                  onClick={(_: any, idx: number) => setSelectedSector(sectors[idx]?.name ?? null)}
                  style={{ cursor: 'pointer' }}
                >
                  {sectors.map((_: any, i: number) => (
                    <Cell
                      key={i}
                      fill={COLORS[i % COLORS.length]}
                      opacity={!activeSector || sectors[i]?.name === activeSector ? 1 : 0.35}
                    />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }}
                  formatter={(v: number) => [fmt$(v, 0), 'Value']}
                />
              </PieChart>
            </ResponsiveContainer>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 280, overflowY: 'auto' }}>
            {sectors.map((s, i) => {
              const pct = s.pct != null ? Number(s.pct) : (total > 0 ? (s.value / total) * 100 : 0)
              const sel = s.name === activeSector
              return (
                <button
                  key={s.name}
                  type="button"
                  data-testid={`sector-row-${s.name.replace(/\W+/g, '-').toLowerCase()}`}
                  onClick={() => setSelectedSector(s.name)}
                  style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8,
                    padding: '6px 8px', borderRadius: 6, cursor: 'pointer', textAlign: 'left',
                    border: `1px solid ${sel ? COLORS[i % COLORS.length] : 'transparent'}`,
                    background: sel ? `${COLORS[i % COLORS.length]}18` : 'transparent',
                    fontSize: 11,
                  }}
                >
                  <span style={{ color: COLORS[i % COLORS.length], fontWeight: sel ? 800 : 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {s.name}
                  </span>
                  <span style={{ color: 'var(--text2)', fontFamily: 'monospace', flexShrink: 0 }}>
                    {fmt$(s.value, 0)} · {pct.toFixed(1)}%
                  </span>
                </button>
              )
            })}
          </div>
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/overview sectors · holdings for account split</div>
        </div>

        {/* Selected sector detail */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
            <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', marginBottom: 4 }}>
              {activeSector || 'Select a sector'}
              {activeTotal > 0 && (
                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text2)', marginLeft: 8, fontFamily: 'monospace' }}>
                  {fmt$(activeTotal, 0)}
                </span>
              )}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 12 }}>
              Where this sector lives (by brokerage account)
            </div>
            {activeAcctRows.length === 0 ? (
              <div style={{ fontSize: 11, color: 'var(--text3)' }}>No holdings tagged to this sector in the current holdings feed.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {activeAcctRows.map(([acct, val]) => {
                  const pct = activeTotal > 0 ? (val / activeTotal) * 100 : 0
                  return (
                    <div key={acct}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 3 }}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--text1)', fontWeight: 700 }}>
                          <span style={{ width: 8, height: 8, borderRadius: '50%', background: acctColor(acct) }} />
                          {acctLabel(acct)}
                        </span>
                        <span style={{ fontFamily: 'monospace', color: 'var(--text2)' }}>
                          {fmt$(val, 0)} · {pct.toFixed(0)}%
                        </span>
                      </div>
                      <div style={{ height: 6, borderRadius: 3, background: 'var(--bg0)', overflow: 'hidden' }}>
                        <div style={{ width: `${pct}%`, height: '100%', background: acctColor(acct), borderRadius: 3 }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            )}

            {/* overview sectors_by_account cross-check when present */}
            {accounts.length > 0 && activeSector && (
              <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
                <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--text3)', textTransform: 'uppercase', marginBottom: 6 }}>
                  Overview feed (sectors_by_account)
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                  {accounts.map(a => {
                    const row = (sectorsByAccount[a] || []).find(s => s.name === activeSector)
                    if (!row) return null
                    return (
                      <span key={a} style={{
                        fontSize: 10, padding: '3px 8px', borderRadius: 6,
                        background: `${acctColor(a)}18`, border: `1px solid ${acctColor(a)}44`, color: 'var(--text2)',
                      }}>
                        {acctLabel(a)} · {fmt$(row.value, 0)}
                      </span>
                    )
                  })}
                </div>
              </div>
            )}
          </div>

          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, flex: 1 }}>
            <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)', marginBottom: 8 }}>
              Holdings in {activeSector || '—'}
              <span style={{ fontWeight: 600, color: 'var(--text3)', marginLeft: 8 }}>{activeHoldings.length}</span>
            </div>
            {activeHoldings.length === 0 ? (
              <div style={{ fontSize: 11, color: 'var(--text3)' }}>No line items for this sector.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 360, overflowY: 'auto' }}>
                {activeHoldings.map(h => (
                  <button
                    key={`${h.symbol}:${h.account}`}
                    type="button"
                    onClick={() => onOpenHolding?.(h.symbol, h.account)}
                    style={{
                      display: 'grid', gridTemplateColumns: '72px 1fr auto', gap: 10, alignItems: 'center',
                      padding: '7px 10px', borderRadius: 6, border: '1px solid var(--border)',
                      background: 'var(--bg2)', cursor: onOpenHolding ? 'pointer' : 'default', textAlign: 'left',
                    }}
                  >
                    <span style={{ fontFamily: 'monospace', fontWeight: 800, color: 'var(--text0)', fontSize: 12 }}>{h.symbol}</span>
                    <span style={{ fontSize: 10, color: 'var(--text3)', display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                      <span style={{ width: 6, height: 6, borderRadius: '50%', background: acctColor(h.account) }} />
                      {acctLabel(h.account)}
                      {h.shares > 0 && <span>· {h.shares} sh</span>}
                    </span>
                    <span style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color: 'var(--text1)' }}>{fmt$(h.value, 0)}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {sectors.length > 0 && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
          <RiskHeatmapGrid
            title="Sector exposure heatmap"
            valueLabel="allocation"
            columns={4}
            cells={sectors.slice(0, 12).map((s) => ({
              key: s.name,
              label: s.name,
              value: Number(s.value) || 0,
              sub: s.pct != null ? `${s.pct}%` : (total > 0 ? `${((s.value / total) * 100).toFixed(1)}%` : undefined),
            }))}
          />
        </div>
      )}
    </div>
  )
}
