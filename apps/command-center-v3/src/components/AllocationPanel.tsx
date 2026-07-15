import { useMemo, useState } from 'react'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'
import { fmt$ } from '../lib/format'
import { normalizeSectorLabel } from '../lib/sectorNormalize'
import RiskHeatmapGrid from './risk/RiskHeatmapGrid'

const COLORS = ['#60a5fa', '#22c55e', '#f59e0b', '#a855f7', '#ef4444', '#06b6d4', '#e879f9', '#fb923c', '#34d399', '#f472b6']

type SectorRow = { name: string; value: number; pct?: number }
type SectorContributor = {
  symbol: string; account: string; method?: string; value: number; pct_of_sector?: number
}
type SectorUnderlying = {
  symbol: string; value: number; pct_of_sector?: number; via?: string[]
}

interface Props {
  sectors: SectorRow[]
  sectorsByAccount?: Record<string, SectorRow[]>
  /** sector name → positions that feed look-through allocation */
  sectorContributors?: Record<string, SectorContributor[]>
  /** sector name → underlying stocks inside funds */
  sectorUnderlyings?: Record<string, SectorUnderlying[]>
  lookthroughAsOf?: string | null
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
 *
 * Overview donut uses look-through GICS names (resolved_sectors). Holdings rows
 * carry Yahoo/Finviz short tags ("Financial") — normalize before matching.
 */
export default function AllocationPanel({
  sectors, sectorsByAccount = {}, sectorContributors = {}, sectorUnderlyings = {},
  lookthroughAsOf, holdings, acctColor, onOpenHolding, onGoHoldings,
}: Props) {
  const [selectedSector, setSelectedSector] = useState<string | null>(null)
  const total = useMemo(() => sectors.reduce((s, x) => s + (Number(x.value) || 0), 0), [sectors])
  const accounts = useMemo(() => Object.keys(sectorsByAccount).sort(), [sectorsByAccount])

  // Look-through contributor map keyed by canonical sector name
  const contributorsBySector = useMemo(() => {
    const m: Record<string, SectorContributor[]> = {}
    for (const [k, rows] of Object.entries(sectorContributors || {})) {
      m[normalizeSectorLabel(k)] = (rows || []).slice().sort((a, b) => (b.value || 0) - (a.value || 0))
    }
    return m
  }, [sectorContributors])
  const underlyingsBySector = useMemo(() => {
    const m: Record<string, SectorUnderlying[]> = {}
    for (const [k, rows] of Object.entries(sectorUnderlyings || {})) {
      m[normalizeSectorLabel(k)] = (rows || []).slice().sort((a, b) => (b.value || 0) - (a.value || 0))
    }
    return m
  }, [sectorUnderlyings])

  // sector → account → $ from live holdings (normalized sector labels)
  const { bySectorAcct, sectorHoldings } = useMemo(() => {
    const by: Record<string, Record<string, number>> = {}
    const sh: Record<string, { symbol: string; account: string; value: number; shares: number; rawSector: string }[]> = {}
    for (const h of holdings || []) {
      if (h?.is_cash) continue
      const raw = String(h.sector || h.sector_type || '').trim()
      const sector = normalizeSectorLabel(raw || 'Other / Unclassified')
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
        rawSector: raw || '—',
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
  const activeCanon = activeSector ? normalizeSectorLabel(activeSector) : null
  const activeHoldings = activeCanon ? (sectorHoldings[activeCanon] || []) : []

  // Account mix: prefer look-through contributors (accurate for funds), then tagged holdings, then overview sba
  const activeAcctMix = useMemo(() => {
    if (!activeCanon) return {} as Record<string, number>
    const fromContrib: Record<string, number> = {}
    for (const c of contributorsBySector[activeCanon] || []) {
      const a = String(c.account || 'unknown')
      fromContrib[a] = (fromContrib[a] || 0) + (Number(c.value) || 0)
    }
    if (Object.keys(fromContrib).length > 0) return fromContrib
    const fromHoldings = bySectorAcct[activeCanon] || {}
    if (Object.keys(fromHoldings).length > 0) return fromHoldings
    const fromOverview: Record<string, number> = {}
    for (const acct of accounts) {
      const row = (sectorsByAccount[acct] || []).find(s => normalizeSectorLabel(s.name) === activeCanon)
      if (row && Number(row.value) > 0) fromOverview[acct] = Number(row.value)
    }
    return fromOverview
  }, [activeCanon, contributorsBySector, bySectorAcct, accounts, sectorsByAccount])

  const activeAcctRows = Object.entries(activeAcctMix).sort((a, b) => b[1] - a[1])
  const activeTotal = activeAcctRows.reduce((s, [, v]) => s + v, 0)
  const activeContributors = activeCanon ? (contributorsBySector[activeCanon] || []) : []
  const activeUnderlyings = activeCanon ? (underlyingsBySector[activeCanon] || []) : []
  const acctMixFromLookthrough = activeContributors.some(c => c.method === 'lookthrough')
    || (activeCanon && Object.keys(bySectorAcct[activeCanon] || {}).length === 0 && activeAcctRows.length > 0)
  const overviewSectorValue = useMemo(() => {
    if (!activeCanon) return 0
    const hit = sectors.find(s => normalizeSectorLabel(s.name) === activeCanon)
    return Number(hit?.value) || 0
  }, [sectors, activeCanon])

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
            Click a sector for look-through contributors + underlyings. Total invested · {fmt$(total, 0)}.
            {lookthroughAsOf && (
              <span style={{ display: 'block', marginTop: 4, color: '#94a3b8' }}>
                Look-through as of <b style={{ color: 'var(--text2)' }}>{lookthroughAsOf}</b>
                {' · '}refreshes <b style={{ color: 'var(--text2)' }}>weekdays 16:10 ET</b> (post-close) after reprice
                {' · '}prices reprice ~every 15m; share sizes update on Schwab/SnapTrade sync.
              </span>
            )}
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
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>
            Source: look-through sectors (overview) · holdings tags (normalized Yahoo→GICS) for line items
          </div>
        </div>

        {/* Selected sector detail */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
            <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', marginBottom: 4 }}>
              {activeSector || 'Select a sector'}
              {(activeTotal > 0 || overviewSectorValue > 0) && (
                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text2)', marginLeft: 8, fontFamily: 'monospace' }}>
                  {fmt$(activeTotal > 0 ? activeTotal : overviewSectorValue, 0)}
                </span>
              )}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 12 }}>
              Where this sector lives (by brokerage account)
              {acctMixFromLookthrough && (
                <span style={{ color: '#f59e0b', fontWeight: 700 }}> · look-through (fund underlyings)</span>
              )}
            </div>
            {activeAcctRows.length === 0 ? (
              <div style={{ fontSize: 11, color: 'var(--text3)' }}>
                No account split for this sector yet (overview look-through + holdings tags empty).
              </div>
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
            {acctMixFromLookthrough && (
              <div style={{ marginTop: 10, fontSize: 10, color: 'var(--text3)', lineHeight: 1.45 }}>
                Account $ from overview look-through (ETFs/funds decomposed). Direct ticker tags may not list every contributor.
              </div>
            )}
          </div>

          {/* Look-through contributors (positions whose MV flows into this sector) */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, flex: 1 }}>
            <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)', marginBottom: 4 }}>
              Contributors to {activeSector || '—'}
              <span style={{ fontWeight: 600, color: 'var(--text3)', marginLeft: 8 }}>
                {activeContributors.length || activeHoldings.length}
              </span>
            </div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 8, lineHeight: 1.4 }}>
              Positions allocating dollars into this sector (ETF slice or direct stock). Click → Holdings.
            </div>
            {activeContributors.length === 0 && activeHoldings.length === 0 ? (
              <div style={{ fontSize: 11, color: 'var(--text3)', lineHeight: 1.5 }}>
                {overviewSectorValue > 0
                  ? `Exposure ${fmt$(overviewSectorValue, 0)} is on the books, but contributor list is empty — re-run look-through resolver.`
                  : 'No line items for this sector.'}
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 280, overflowY: 'auto' }}>
                {(activeContributors.length > 0
                  ? activeContributors.map(c => ({
                    symbol: c.symbol,
                    account: c.account,
                    value: c.value,
                    method: c.method,
                    pct: c.pct_of_sector,
                    shares: 0,
                  }))
                  : activeHoldings.map(h => ({
                    symbol: h.symbol,
                    account: h.account,
                    value: h.value,
                    method: 'tag',
                    pct: undefined as number | undefined,
                    shares: h.shares,
                  }))
                ).map(h => (
                  <button
                    key={`${h.symbol}:${h.account}:${h.method || ''}`}
                    type="button"
                    data-testid={`allocation-holding-${h.symbol}`}
                    onClick={() => onOpenHolding?.(h.symbol, h.account)}
                    style={{
                      display: 'grid', gridTemplateColumns: '64px 1fr auto', gap: 8, alignItems: 'center',
                      padding: '7px 10px', borderRadius: 6, border: '1px solid var(--border)',
                      background: 'var(--bg2)', cursor: onOpenHolding ? 'pointer' : 'default', textAlign: 'left',
                    }}
                  >
                    <span style={{ fontFamily: 'monospace', fontWeight: 800, color: 'var(--text0)', fontSize: 12 }}>{h.symbol}</span>
                    <span style={{ fontSize: 10, color: 'var(--text3)', display: 'inline-flex', alignItems: 'center', gap: 5, flexWrap: 'wrap' }}>
                      <span style={{ width: 6, height: 6, borderRadius: '50%', background: acctColor(h.account) }} />
                      {acctLabel(h.account)}
                      {h.method && h.method !== 'tag' && (
                        <span style={{
                          fontSize: 8.5, fontWeight: 800, padding: '1px 5px', borderRadius: 3,
                          background: h.method === 'lookthrough' ? 'rgba(96,165,250,.15)' : 'rgba(34,197,94,.12)',
                          color: h.method === 'lookthrough' ? '#60a5fa' : '#22c55e',
                        }}>
                          {h.method === 'lookthrough' ? 'fund slice' : h.method === 'direct_stock' ? 'direct' : h.method}
                        </span>
                      )}
                      {h.pct != null && <span>· {Number(h.pct).toFixed(1)}% of sector</span>}
                      {h.shares > 0 && <span>· {h.shares} sh</span>}
                    </span>
                    <span style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color: 'var(--text1)' }}>{fmt$(h.value, 0)}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Underlying stocks inside funds (look-through names) */}
          {activeUnderlyings.length > 0 && (
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 800, color: 'var(--text0)', marginBottom: 4 }}>
                Top underlyings in {activeSector || '—'}
                <span style={{ fontWeight: 600, color: 'var(--text3)', marginLeft: 8 }}>{activeUnderlyings.length}</span>
              </div>
              <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 8 }}>
                Stocks inside held ETFs/funds (top holdings × position size). Via = source fund(s).
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3, maxHeight: 220, overflowY: 'auto' }}>
                {activeUnderlyings.map(u => (
                  <div
                    key={u.symbol}
                    data-testid={`allocation-underlying-${u.symbol}`}
                    style={{
                      display: 'grid', gridTemplateColumns: '64px 1fr auto', gap: 8, alignItems: 'center',
                      padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)',
                    }}
                  >
                    <span style={{ fontFamily: 'monospace', fontWeight: 800, color: '#a855f7', fontSize: 12 }}>{u.symbol}</span>
                    <span style={{ fontSize: 10, color: 'var(--text3)' }}>
                      via {(u.via || []).join(', ') || '—'}
                      {u.pct_of_sector != null && <span> · {Number(u.pct_of_sector).toFixed(1)}% of sector</span>}
                    </span>
                    <span style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color: 'var(--text1)' }}>{fmt$(u.value, 0)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
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
