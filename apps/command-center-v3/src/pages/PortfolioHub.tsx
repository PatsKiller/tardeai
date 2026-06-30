import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts'
import { fmt$ } from '../lib/format'
import { pricingStampLine } from '../lib/pricingStamp'
import type { DrillContext } from '../components/DetailDrawer'
import ProAnalystPill, { useProAnalystMap } from '../components/ProAnalystPill'
import AnalystReviews, { useAnalystMap } from '../components/AnalystReviews'
import AskAgents from '../components/AskAgents'
import HoldingProtectionActions from '../components/HoldingProtectionActions'
import HoldingReportLinks from '../components/HoldingReportLinks'
import { useAnalystReportMap } from '../hooks/useAnalystReportMap'
import { holdingReportEligible } from '../lib/reportLinks'
import RiskHeatmapGrid from '../components/risk/RiskHeatmapGrid'
import RiskContributionBars from '../components/risk/RiskContributionBars'
import DrawdownChart from '../components/risk/DrawdownChart'

interface Props { onDrill: (ctx: DrillContext) => void }
const TABS = ['Holdings', 'Look-through', 'Returns', 'Dividends', 'Forecast', 'Tax'] as const
const COLORS = ['#60a5fa', '#22c55e', '#f59e0b', '#a855f7', '#ef4444', '#06b6d4', '#e879f9', '#fb923c']

const ACCT_COLORS = ['#60a5fa', '#22c55e', '#f59e0b', '#a855f7', '#ef4444', '#06b6d4', '#e879f9']

// Row at-a-glance helpers
const rsiZoneColor = (s?: string) => s === 'oversold' ? '#22c55e' : s === 'overbought' ? '#f59e0b' : 'var(--text3)'
const signalColor = (s?: string) => {
  const t = (s || '').toUpperCase()
  if (['ADD', 'BUY', 'STRONG_BUY', 'ACCUMULATE'].includes(t)) return '#22c55e'
  if (['TRIM', 'SELL', 'REDUCE', 'EXIT'].includes(t)) return '#ef4444'
  if (['MONITOR', 'WATCH', 'CAUTION'].includes(t)) return '#f59e0b'
  return 'var(--text3)'   // HOLD / NEUTRAL
}
// Unrealized P/L ($ and %) where real cost basis exists (401k funds have none → null → "—")
const plMetrics = (h: any): { dollars: number | null; pct: number | null } => {
  const cb = h.cost_basis
  if (cb == null || cb <= 0) return { dollars: null, pct: null }
  const dollars = h.gain_loss != null
    ? Number(h.gain_loss)
    : (h.market_value != null ? Number(h.market_value) - Number(cb) : null)
  const pct = h.gain_loss_pct != null
    ? Number(h.gain_loss_pct)
    : (dollars != null ? (dollars / Number(cb)) * 100 : null)
  return { dollars, pct }
}

// ── signal sub-tab buckets (operator request 2026-06-12) ──
const SIGNAL_TABS: [string, string[]][] = [
  ['All', []],
  ['Buy/Add', ['ADD', 'BUY', 'STRONG_BUY', 'ACCUMULATE']],
  ['Hold', ['HOLD', 'NEUTRAL']],
  ['Watch', ['WATCH', 'MONITOR', 'CAUTION']],
  ['Trim/Sell', ['TRIM', 'SELL', 'REDUCE', 'EXIT']],
]
const PAGE_SIZE = 12

// LLM provenance badge styling — which model lane reviewed this symbol (advisory research only)
const LLM_LANE: Record<string, { label: string; c: string }> = {
  local: { label: 'GEMMA', c: '#2dd4bf' },
  grok: { label: 'GROK', c: '#f59e0b' },
  chatgpt: { label: 'GPT', c: '#a3e635' },
  claude: { label: 'CLAUDE', c: '#d97757' },
}
function LlmBadges({ cov }: { cov?: any[] }) {
  if (!cov?.length) return <span title="no LLM research touched this symbol in 30d" style={{ fontSize: 8, color: 'var(--text3)' }}>no LLM review</span>
  const byLane: Record<string, any> = {}
  for (const c of cov) {
    const k = LLM_LANE[c.lane] ? c.lane : 'local'
    if (!byLane[k] || c.last_at > byLane[k].last_at) byLane[k] = c
  }
  return (
    <span style={{ display: 'inline-flex', gap: 3, flexWrap: 'wrap' }}>
      {Object.entries(byLane).map(([lane, c]: any) => {
        const m = LLM_LANE[lane]
        return <span key={lane} title={`${c.model} · ${String(c.last_at).slice(0, 10)} · ${c.n} review${c.n > 1 ? 's' : ''} (advisory research)`}
          style={{ fontSize: 7.5, fontWeight: 800, padding: '1px 5px', borderRadius: 3, letterSpacing: 0.4,
            background: m.c + '1f', color: m.c, border: `1px solid ${m.c}44`, cursor: 'help' }}>
          🤖 {m.label}</span>
      })}
    </span>
  )
}

export default function PortfolioHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Holdings')
  const [acctFilter, setAcctFilter] = useState<string | null>(null)
  const [sigTab, setSigTab] = useState('All')
  const [page, setPage] = useState(0)
  // Diversification gap-fill: LLM design-for-approval + per-ETF propose state
  const [gapDesign, setGapDesign] = useState<any>(null)
  const [gapBusy, setGapBusy] = useState(false)
  const [gapPropose, setGapPropose] = useState<Record<string, string>>({})
  async function designFill() {
    setGapBusy(true); setGapDesign(null)
    try {
      const r = await fetch('/api/v2/lookthrough/design-fill', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      setGapDesign(await r.json())
    } catch { setGapDesign({ ok: false, error: 'request failed' }) }
    setGapBusy(false)
  }
  async function proposeGapEtf(symbol: string, sleeve: string, rationale: string) {
    setGapPropose(p => ({ ...p, [symbol]: '…' }))
    try {
      const r = await fetch('/api/v2/rotation/propose-etf', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol, direction: 'long', instrument_type: 'etf', sleeve, rationale }) })
      const j = await r.json()
      setGapPropose(p => ({ ...p, [symbol]: j?.ok ? (j.already_exists ? 'exists' : 'proposed ✓') : 'error' }))
    } catch { setGapPropose(p => ({ ...p, [symbol]: 'error' })) }
  }
  const { data: overview } = useApi<any>('/api/v2/overview', 60_000)
  const { data: holdings } = useApi<any>('/api/v2/portfolio/holdings', 60_000)
  const { data: llmCov } = useApi<any>('/api/v2/portfolio/llm-coverage', 300_000)
  const { data: monitoredStops, refetch: refetchMonitored } = useApi<any>('/api/v2/holdings/monitored-stops', 60_000)
  const { data: scards } = useApi<any>('/api/v2/symbol-cards', 300_000)
  const cardMap: Record<string, any> = (scards as any)?.cards ?? {}
  const paMap = useProAnalystMap()
  const aMap = useAnalystMap()
  const { data: fvStrip } = useApi<any>('/api/v2/finviz-strip-map', 300_000)
  const fvMap: Record<string, any> = fvStrip?.map ?? {}
  const { data: divs } = useApi<any>('/api/v2/dividends', 120_000)
  const { data: taxLots } = useApi<any>('/api/v2/tax-lots', 120_000)
  const { data: perfData } = useApi<any>('/api/v2/portfolio/performance', 120_000)
  const { data: riskData } = useApi<any>('/api/v2/risk', 120_000)
  const { data: forecast } = useApi<any>('/api/v2/forecast', 300_000)
  const { data: lookthrough } = useApi<any>('/api/v2/portfolio/lookthrough', 300_000)
  const { data: rotation } = useApi<any>('/api/v2/rotation/summary', 300_000)
  const reportMap = useAnalystReportMap()

  // Allocation follows the account filter: per-account look-through when an account is selected, else global.
  const sectorsByAccount = overview?.sectors_by_account ?? {}
  const sectors = (acctFilter && sectorsByAccount[acctFilter]) ? sectorsByAccount[acctFilter] : (overview?.sectors ?? [])
  const allHoldings = holdings?.holdings ?? []
  const payers = divs?.payers ?? []

  // ── Account filter: chips derived from holdings, with per-account counts + value ──
  const acctMap: Record<string, { n: number; value: number }> = {}
  for (const h of allHoldings) {
    const a = h.account ?? 'unknown'
    acctMap[a] ??= { n: 0, value: 0 }
    acctMap[a].n++; acctMap[a].value += (h.market_value ?? 0)
  }
  const accounts = Object.entries(acctMap).sort((a, b) => b[1].value - a[1].value)
  const acctColor = (a: string) => ACCT_COLORS[Math.max(0, accounts.findIndex(([k]) => k === a)) % ACCT_COLORS.length]
  const acctFiltered = acctFilter ? allHoldings.filter((h: any) => (h.account ?? 'unknown') === acctFilter) : allHoldings
  // signal sub-tab filter + per-bucket counts
  const sigCount = (sigs: string[]) => sigs.length === 0 ? acctFiltered.length
    : acctFiltered.filter((h: any) => sigs.includes(String(h.signal || '').toUpperCase())).length
  const sigSet = SIGNAL_TABS.find(([k]) => k === sigTab)?.[1] ?? []
  const holdingsList = (sigSet.length === 0 ? acctFiltered
    : acctFiltered.filter((h: any) => sigSet.includes(String(h.signal || '').toUpperCase())))
    .slice().sort((a: any, b: any) => (b.market_value ?? 0) - (a.market_value ?? 0))
  const pages = Math.max(1, Math.ceil(holdingsList.length / PAGE_SIZE))
  const pageClamped = Math.min(page, pages - 1)
  const pageRows = holdingsList.slice(pageClamped * PAGE_SIZE, (pageClamped + 1) * PAGE_SIZE)
  const coverage: Record<string, any[]> = (llmCov as any)?.coverage ?? {}
  const protection: Record<string, any> = (llmCov as any)?.protection ?? {}
  const monitoredByKey: Record<string, any> = monitoredStops?.by_key ?? {}
  const confirmedByKey: Record<string, any> = (llmCov as any)?.confirmed_stops ?? {}
  // Header total + day P/L follow the active filter (account + signal). Unfiltered → equals the global
  // portfolio figures; filtered → that account's own value + day change (fixes "10 holdings · $1.25M").
  const viewTotal = holdingsList.reduce((s: number, h: any) => s + (h.market_value ?? 0), 0)
  const viewDay = holdingsList.reduce((s: number, h: any) =>
    s + (h.day_change ?? (h.market_value ?? 0) * (h.day_change_pct ?? 0) / 100), 0)
  const viewDayPct = (viewTotal - viewDay) ? viewDay / (viewTotal - viewDay) * 100 : 0
  const priceStamp = pricingStampLine(holdings?.pricing ?? holdings, { includeTechnicals: true })

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Portfolio</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{holdingsList.length} holdings · {fmt$(viewTotal, 0)}
            {' · '}<span style={{ color: viewDay >= 0 ? '#22c55e' : '#ef4444' }}>today {viewDay >= 0 ? '+' : ''}{fmt$(viewDay, 0)} ({viewDay >= 0 ? '+' : ''}{viewDayPct.toFixed(2)}%)</span>
            {acctFilter && <span style={{ color: 'var(--text4)' }}> · {acctFilter.replace(/_/g, ' ')}</span>}</div>
          {priceStamp && (
            <div
              title={holdings?.pricing?.note ?? 'Live price overlay per account: Schwab broker sync; Fidelity Finviz/market_quotes'}
              onClick={() => onDrill({ title: 'Pricing sources', subtitle: priceStamp, endpoint: '/api/v2/portfolio/holdings',
                rows: holdings?.pricing ? [holdings.pricing] : [{ last_repriced: holdings?.last_repriced, reprice_source: holdings?.reprice_source }] })}
              style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4, cursor: 'pointer' }}
            >{priceStamp}</div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
              color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
            }}>{t}</button>
          ))}
        </div>
      </div>

      {tab === 'Holdings' && (() => {
        const rs = rotation?.summary ?? {}
        const noAction = (rs.rotation_ideas ?? 0) === 0 && (rs.trim_review ?? 0) === 0 && (rs.add_review ?? 0) === 0
        return (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 12, padding: '10px 14px',
            background: 'var(--bg1)', border: '1px solid var(--border)', borderLeft: '4px solid #60a5fa', borderRadius: 10,
          }}>
            <div style={{ flex: 1, minWidth: 220 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)' }}>Rotation Advisor
                <span style={{ fontSize: 8.5, color: '#f59e0b', fontWeight: 600, marginLeft: 8 }}>advisory only · no broker action</span>
              </div>
              <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 2 }}>
                Account-aware rotation review with a local + Grok OAuth second opinion.
                {rotation && noAction
                  ? <span style={{ color: '#f59e0b' }}> No model-supported action — WATCH / RESEARCH_MORE.</span>
                  : rotation
                    ? <span> {rs.trim_review ?? 0} trim · {rs.add_review ?? 0} add · {rs.rotation_ideas ?? 0} rotation to review.</span>
                    : null}
              </div>
            </div>
            <a href="/v3/rotation" style={{
              padding: '6px 14px', fontSize: 11, fontWeight: 700, borderRadius: 6, textDecoration: 'none',
              background: 'rgba(96,165,250,.15)', color: '#60a5fa', border: '1px solid #60a5fa55', whiteSpace: 'nowrap',
            }}>Open Rotation Review →</a>
          </div>
        )
      })()}

      {tab === 'Holdings' && accounts.length > 1 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12, alignItems: 'center' }}>
          <button onClick={() => setAcctFilter(null)} style={{
            padding: '3px 10px', fontSize: 10, borderRadius: 12, cursor: 'pointer',
            border: `1px solid ${acctFilter === null ? '#60a5fa' : 'var(--border)'}`,
            background: acctFilter === null ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
            color: acctFilter === null ? '#60a5fa' : 'var(--text3)', fontWeight: acctFilter === null ? 700 : 400,
          }}>All ({allHoldings.length})</button>
          {accounts.map(([a, info]) => (
            <button key={a} onClick={() => setAcctFilter(a === acctFilter ? null : a)} style={{
              padding: '3px 10px', fontSize: 10, borderRadius: 12, cursor: 'pointer',
              border: `1px solid ${acctFilter === a ? acctColor(a) : 'var(--border)'}`,
              background: acctFilter === a ? `${acctColor(a)}22` : 'var(--bg2)',
              color: acctFilter === a ? acctColor(a) : 'var(--text3)', fontWeight: acctFilter === a ? 700 : 400,
            }}>
              <span style={{ display: 'inline-block', width: 7, height: 7, borderRadius: '50%', background: acctColor(a), marginRight: 5 }} />
              {a} ({info.n})
            </button>
          ))}
        </div>
      )}

      {tab === 'Holdings' && (
        <div style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: 16 }}>
          {/* Allocation donut */}
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Allocation</div>
            {sectors.length === 0 ? <div style={{ color: 'var(--text3)', fontSize: 11 }}>No sector data</div> : (
              <ResponsiveContainer width="100%" height={200}>
                <PieChart>
                  <Pie data={sectors} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} stroke="var(--bg0)" strokeWidth={2}>
                    {sectors.map((_: any, i: number) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} formatter={(v: number) => [fmt$(v, 0), 'Value']} />
                </PieChart>
              </ResponsiveContainer>
            )}
            {sectors.map((s: any, i: number) => (
              <div key={s.name} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, padding: '2px 0' }}>
                <span style={{ color: COLORS[i % COLORS.length] }}>{s.name}</span>
                <span style={{ color: 'var(--text2)' }}>{fmt$(s.value, 0)}</span>
              </div>
            ))}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Source: /api/v2/overview → sectors</div>
            {sectors.length > 0 && (
              <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
                <RiskHeatmapGrid
                  title="Sector exposure"
                  valueLabel="allocation"
                  columns={2}
                  cells={sectors.slice(0, 8).map((s: any) => ({
                    key: s.name,
                    label: s.name,
                    value: Number(s.value) || 0,
                    sub: s.pct != null ? `${s.pct}%` : undefined,
                  }))}
                />
              </div>
            )}
          </div>

          {/* Holdings — large graphical cards (operator request 2026-06-12) */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, flexWrap: 'wrap', gap: 8 }}>
              {/* signal sub-tab filters */}
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {SIGNAL_TABS.map(([k, sigs]) => {
                  const n = sigCount(sigs)
                  const c = k === 'Buy/Add' ? '#22c55e' : k === 'Trim/Sell' ? '#ef4444' : k === 'Watch' ? '#f59e0b' : '#60a5fa'
                  return (
                    <button key={k} onClick={() => { setSigTab(k); setPage(0) }} style={{
                      padding: '4px 12px', fontSize: 10.5, borderRadius: 6, cursor: 'pointer',
                      border: `1px solid ${sigTab === k ? c : 'var(--border)'}`,
                      background: sigTab === k ? `${c}1f` : 'var(--bg2)',
                      color: sigTab === k ? c : 'var(--text3)', fontWeight: sigTab === k ? 800 : 400,
                    }}>{k} ({n})</button>
                  )
                })}
              </div>
              {priceStamp && <div style={{ fontSize: 8, color: 'var(--text3)' }} title={holdings?.pricing?.note}>{priceStamp}</div>}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(290px,1fr))', gap: 10 }}>
              {pageRows.map((h: any) => {
                const { dollars: pl$, pct: pl } = plMetrics(h)
                const zc = rsiZoneColor(h.rsi_status)
                const sc = signalColor(h.signal)
                const ac = acctColor(h.account ?? 'unknown')
                const dayPct = h.day_change_pct
                return (
                  <div key={`${h.symbol}-${h.account}`}
                    onClick={() => onDrill({ title: h.symbol, subtitle: `${h.account} · ${h.name}`, endpoint: '/api/v2/portfolio/holdings', rows: [h] })}
                    style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderLeft: `4px solid ${sc === 'var(--text3)' ? ac : sc}`,
                      borderRadius: 10, padding: '12px 14px', cursor: 'pointer' }}>
                    {/* header: symbol + signal */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ fontSize: 16, fontWeight: 800, color: 'var(--text0)', fontFamily: 'monospace' }}>{h.symbol}</span>
                      <ProAnalystPill symbol={h.symbol} map={paMap} compact />
                      <span style={{ flex: 1 }} />
                      {/* Card click opens the detail drawer (charts + record + a rotation-review link inside).
                          The inline ⤢ review link was removed — it hijacked card clicks (clicking JEPI/SCHD
                          went straight to the rotation page instead of the drawer). Rotation review now lives
                          IN the drawer, for rotatable holdings only. */}
                      {h.signal
                        ? <span style={{ fontSize: 10, fontWeight: 800, padding: '2px 9px', borderRadius: 4, background: `${sc}1f`, color: sc }}>{h.signal}</span>
                        : <span style={{ fontSize: 9, color: 'var(--text3)' }}>—</span>}
                    </div>
                    <div style={{ fontSize: 8.5, color: 'var(--text3)', marginTop: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{h.name}</div>
                    {/* account badge */}
                    <div style={{ marginTop: 5 }}>
                      <span style={{ fontSize: 8.5, fontWeight: 700, padding: '1px 7px', borderRadius: 3, background: `${ac}1f`, color: ac }}>
                        ● {(h.account ?? 'unknown').replace(/_/g, ' ')}</span>
                    </div>
                    {/* Finviz inline strip */}
                    {fvMap[(h.symbol || '').toUpperCase()] && (() => {
                      const fv = fvMap[(h.symbol || '').toUpperCase()]
                      const pc = (v: any) => v == null ? 'var(--text3)' : Number(v) > 0 ? '#22c55e' : Number(v) < 0 ? '#ef4444' : 'var(--text3)'
                      const rsiC = fv.rsi == null ? 'var(--text3)' : fv.rsi >= 70 ? '#ef4444' : fv.rsi <= 30 ? '#22c55e' : 'var(--text1)'
                      const c = (l: string, v: any, col: string, sfx = '') => <span style={{ fontSize: 8.5, color: 'var(--text3)' }}>{l}<b style={{ color: col, fontFamily: 'monospace' }}>{v == null ? '—' : `${Number(v) > 0 && sfx ? '+' : ''}${Number(v).toFixed(sfx ? 1 : 0)}${sfx}`}</b></span>
                      return <div title="Finviz daily metrics" style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 5, padding: '3px 7px', borderRadius: 6, background: 'rgba(96,165,250,.07)', border: '1px solid rgba(96,165,250,.16)' }}>
                        {c('RSI ', fv.rsi, rsiC)}{c('W ', fv.perf_week, pc(fv.perf_week), '%')}{c('M ', fv.perf_month, pc(fv.perf_month), '%')}{c('YTD ', fv.perf_ytd, pc(fv.perf_ytd), '%')}</div>
                    })()}
                    {/* value + P/L row */}
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginTop: 8, flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 19, fontWeight: 800, color: 'var(--text0)' }}>{fmt$(h.market_value, 0)}</span>
                      {pl$ != null ? (
                        <span style={{ fontSize: 13, fontWeight: 800, color: pl$ >= 0 ? '#22c55e' : '#ef4444' }}
                          title={pl != null ? `Unrealized ${pl >= 0 ? '+' : ''}${pl.toFixed(2)}% on cost basis ${fmt$(h.cost_basis, 0)}` : undefined}>
                          {pl$ >= 0 ? '+' : ''}{fmt$(pl$, 0)}
                          {pl != null && <span style={{ fontSize: 11, fontWeight: 700, opacity: 0.9 }}> ({pl >= 0 ? '+' : ''}{pl.toFixed(1)}%)</span>}
                        </span>
                      ) : (
                        <span style={{ fontSize: 13, fontWeight: 800, color: 'var(--text3)' }}>— P/L</span>
                      )}
                      {dayPct != null && <span style={{ fontSize: 9.5, color: dayPct >= 0 ? '#22c55e' : '#ef4444' }}>today {dayPct >= 0 ? '+' : ''}{Number(dayPct).toFixed(1)}%</span>}
                    </div>
                    {/* per-share current price + purchase (cost-basis) price — operator: show larger */}
                    {(() => {
                      const sh = Number(h.shares) || 0
                      const cur = sh > 0 && h.market_value != null ? Number(h.market_value) / sh : null
                      const buy = sh > 0 && h.cost_basis != null && Number(h.cost_basis) > 0 ? Number(h.cost_basis) / sh : null
                      if (cur == null) return null
                      return (
                        <div style={{ display: 'flex', gap: 14, marginTop: 5, fontSize: 12.5, fontWeight: 700, alignItems: 'baseline', flexWrap: 'wrap' }}>
                          <span style={{ color: 'var(--text2)' }}>Price <b style={{ fontFamily: 'monospace', fontSize: 14, color: 'var(--text0)' }}>${cur.toFixed(2)}</b></span>
                          <span style={{ color: 'var(--text3)' }} title={buy != null ? 'Average purchase price per share (cost basis ÷ shares)' : '401(k) funds carry no per-lot cost basis'}>
                            Cost <b style={{ fontFamily: 'monospace', color: 'var(--text1)' }}>{buy != null ? `$${buy.toFixed(2)}` : '—'}</b></span>
                        </div>
                      )
                    })()}
                    {/* % of portfolio bar */}
                    <div style={{ marginTop: 7, height: 5, background: 'var(--bg2)', borderRadius: 3 }}>
                      <div style={{ width: `${Math.min(100, (h.portfolio_pct ?? 0) * 4)}%`, height: '100%', background: ac, borderRadius: 3, minWidth: 2 }} />
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, color: 'var(--text3)', marginTop: 2 }}>
                      <span>{h.portfolio_pct != null ? `${h.portfolio_pct.toFixed(1)}% of portfolio` : ''}</span>
                      <span>{h.shares != null ? `${h.shares} sh` : ''}</span>
                    </div>
                    {/* chips: RSI + LLM stop/trail advisory + LLM provenance */}
                    <div style={{ display: 'flex', gap: 4, marginTop: 7, alignItems: 'center', flexWrap: 'wrap' }}>
                      {h.rsi != null && (
                        <span title={h.proxy ? `proxy: ${h.proxy.ticker} (${h.proxy.label})` : h.rsi_status}
                          style={{ fontSize: 8.5, fontWeight: 700, padding: '1px 6px', borderRadius: 3, background: `${zc}1a`, color: zc }}>
                          RSI {Math.round(h.rsi)}{h.proxy ? '*' : ''} {h.rsi_status === 'oversold' ? 'buy zone' : h.rsi_status === 'overbought' ? 'caution' : 'neutral'}</span>
                      )}
                      {(() => {
                        const pr = protection[(h.symbol || '').toUpperCase()]
                        return pr ? (
                          <span title={`${pr.rec}\n${pr.rationale ?? ''}\nanalyzed ${String(pr.at).slice(0, 10)} by ${pr.model} · confidence ${pr.confidence ?? '—'} · ADVISORY ONLY`}
                            style={{ fontSize: 11.5, fontWeight: 800, padding: '3px 9px', borderRadius: 5,
                              background: 'rgba(168,85,247,.16)', border: '1px solid rgba(168,85,247,.35)', color: '#a855f7', cursor: 'help' }}>
                            🛡 {pr.stop_price != null
                              ? `stop $${Number(pr.stop_price).toFixed(2)}${pr.stop_distance_pct != null ? ` (${Number(pr.stop_distance_pct).toFixed(1)}% below)` : ''}`
                              : String(pr.rec).split('·')[0].trim()}</span>
                        ) : null
                      })()}
                      <span style={{ flex: 1 }} />
                      <LlmBadges cov={coverage[(h.symbol || '').toUpperCase()]} />
                    </div>
                    {holdingReportEligible(h) && (
                      <div style={{ marginTop: 6 }} onClick={e => e.stopPropagation()}>
                        <HoldingReportLinks
                          symbol={h.symbol}
                          entry={reportMap[(h.symbol || '').toUpperCase()]}
                          reportType={reportMap[(h.symbol || '').toUpperCase()]?.report_type}
                        />
                      </div>
                    )}
                    {(() => {
                      const pr = protection[(h.symbol || '').toUpperCase()] ?? {}
                      const sh = Number(h.shares) || 0
                      const acct = String(h.account ?? '')
                      const schwabSmall = acct.startsWith('schwab') && sh > 0 && sh < 40
                      if (!pr?.stop_price && !schwabSmall) return null
                      const key = `${(h.symbol || '').toUpperCase()}:${h.account}`
                      const mon = monitoredByKey[key]
                      const conf = confirmedByKey[key]
                      return (
                        <HoldingProtectionActions
                          h={h}
                          pr={pr}
                          monitored={mon}
                          confirmedStop={conf}
                          onRefresh={() => refetchMonitored?.()}
                        />
                      )
                    })()}
                    {/* unified info block (operator 2026-06-12): what it does · sector vs sector · analyst · news */}
                    {(() => {
                      const sc = cardMap[(h.symbol || '').toUpperCase()]
                      if (!sc) return null
                      return (
                        <div style={{ borderTop: '1px solid var(--border)', marginTop: 7, paddingTop: 6, display: 'flex', flexDirection: 'column', gap: 3 }}>
                          {sc.description && <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.5 }}>{sc.description}</div>}
                          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', fontSize: 8.5 }}>
                            {sc.sector && <span style={{ color: '#60a5fa' }}>{sc.sector}{sc.sector_etf ? ` (${sc.sector_etf})` : ''}</span>}
                            {sc.vs_sector_week != null && <span title={`symbol ${sc.perf_week}% vs ${sc.sector_etf} ${sc.sector_perf_week}% (week)`}
                              style={{ color: sc.vs_sector_week >= 0 ? '#22c55e' : '#ef4444', fontWeight: 700 }}>
                              {sc.vs_sector_week >= 0 ? '+' : ''}{sc.vs_sector_week}% vs sector</span>}
                            {sc.analyst?.rating && <span title={`Yahoo consensus ${sc.analyst.mean} · target range $${sc.analyst.target_low}–$${sc.analyst.target_high}${sc.analyst.distribution ? ` · votes: ${sc.analyst.distribution.strong_buy ?? 0} strong buy / ${sc.analyst.distribution.buy ?? 0} buy / ${sc.analyst.distribution.hold ?? 0} hold / ${sc.analyst.distribution.sell ?? 0} sell` : ''}`}
                              style={{ color: String(sc.analyst.rating).includes('buy') ? '#22c55e' : 'var(--text2)' }}>
                              {String(sc.analyst.rating).replace('_', ' ')} · {sc.analyst.opinions} analysts · target ${sc.analyst.target}{sc.analyst.upside_pct != null ? ` (${sc.analyst.upside_pct >= 0 ? '+' : ''}${sc.analyst.upside_pct}%)` : ''}</span>}
                            {sc.earnings && (sc.earnings.next_date || sc.earnings.surprise_pct != null) && (
                              <span title={`${sc.earnings.next_date ? `Next earnings ${sc.earnings.next_date}` : ''}${sc.earnings.last_date ? ` · last ${sc.earnings.last_date}: est ${sc.earnings.eps_estimate} → actual ${sc.earnings.eps_actual}` : ''}`}>
                                {sc.earnings.next_date && <span style={{ color: 'var(--text2)' }}>📅 {new Date(sc.earnings.next_date + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>}
                                {sc.earnings.surprise_pct != null && <span style={{ color: sc.earnings.beat ? '#22c55e' : '#ef4444', fontWeight: 700, marginLeft: sc.earnings.next_date ? 4 : 0 }}>{sc.earnings.next_date ? '· ' : ''}{sc.earnings.beat ? 'BEAT' : 'MISS'} {sc.earnings.surprise_pct >= 0 ? '+' : ''}{sc.earnings.surprise_pct}%</span>}
                              </span>
                            )}
                            {/* Distribution — the fund/ETF analog of earnings (funds have no EPS) */}
                            {sc.distribution && (sc.distribution.next_est || sc.distribution.last_date) && (
                              <span style={{ color: 'var(--text2)' }} title={`${sc.distribution.cadence ? sc.distribution.cadence + ' distribution' : 'distribution'}${sc.distribution.last_date ? ` · last ${sc.distribution.last_date} $${sc.distribution.last_amount}` : ''}${sc.distribution.ttm_amount != null ? ` · TTM $${sc.distribution.ttm_amount}/sh` : ''}${sc.distribution.next_est ? ' · next date estimated from cadence' : ''}`}>
                                💵 {sc.distribution.next_est
                                  ? `next ~${new Date(sc.distribution.next_est + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`
                                  : sc.distribution.cadence || 'distribution'}
                                {sc.distribution.cadence && sc.distribution.next_est ? ` (${sc.distribution.cadence})` : ''}</span>
                            )}
                          </div>
                          <AnalystReviews symbol={h.symbol} map={aMap} />
                          {(sc.news ?? []).slice(0, 3).map((n: any, i: number) => (
                            <div key={i} style={{ fontSize: 8.5, lineHeight: 1.35, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                              <span style={{ color: 'var(--text3)' }}>{n.source} · </span>
                              {n.url ? <a href={n.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={{ color: '#93c5fd', textDecoration: 'none' }} title={n.title}>{n.title}</a>
                                : <span style={{ color: 'var(--text2)' }} title={n.title}>{n.title}</span>}
                            </div>
                          ))}
                        </div>
                      )
                    })()}
                  </div>
                )
              })}
            </div>
            {holdingsList.length === 0 && <div style={{ padding: 20, color: 'var(--text3)', fontSize: 11, textAlign: 'center', background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10 }}>No holdings match this filter.</div>}

            {/* pagination */}
            {pages > 1 && (
              <div style={{ display: 'flex', gap: 5, justifyContent: 'center', alignItems: 'center', marginTop: 12 }}>
                <button disabled={pageClamped === 0} onClick={() => setPage(p => Math.max(0, p - 1))}
                  style={{ fontSize: 11, padding: '3px 12px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: pageClamped === 0 ? 'var(--text3)' : '#60a5fa', cursor: 'pointer' }}>‹ prev</button>
                {Array.from({ length: pages }, (_, i) => (
                  <button key={i} onClick={() => setPage(i)} style={{
                    fontSize: 10.5, padding: '3px 9px', borderRadius: 5, cursor: 'pointer',
                    border: `1px solid ${i === pageClamped ? '#60a5fa' : 'var(--border)'}`,
                    background: i === pageClamped ? 'rgba(96,165,250,.18)' : 'var(--bg2)',
                    color: i === pageClamped ? '#60a5fa' : 'var(--text3)', fontWeight: i === pageClamped ? 800 : 400 }}>{i + 1}</button>
                ))}
                <button disabled={pageClamped >= pages - 1} onClick={() => setPage(p => Math.min(pages - 1, p + 1))}
                  style={{ fontSize: 11, padding: '3px 12px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: pageClamped >= pages - 1 ? 'var(--text3)' : '#60a5fa', cursor: 'pointer' }}>next ›</button>
                <span style={{ fontSize: 9, color: 'var(--text3)', marginLeft: 8 }}>{holdingsList.length} holdings · {PAGE_SIZE}/page</span>
              </div>
            )}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>
              P/L ($ and %) shown where cost basis exists (csv tax lot &gt; broker API); 401(k) funds carry no per-lot basis → "—". RSI * = public-ETF proxy.
              🤖 badges = which LLM lane reviewed the symbol in the last 30d (advisory research, never an execution signal) · source: /api/v2/portfolio/llm-coverage. Card click = full drawer.
            </div>
          </div>
        </div>
      )}

      {tab === 'Look-through' && (() => {
        const lt = (lookthrough as any)?.data ?? lookthrough ?? {}
        const acctDetail = lt.accounts_detail ?? {}
        // account filter: per-account look-through when selected, else portfolio-wide
        const view = (acctFilter && acctDetail[acctFilter]) ? acctDetail[acctFilter] : lt
        const themes = Object.entries(view.themes ?? {}).map(([name, t]: any) => ({ name, ...t })).sort((a: any, b: any) => b.pct - a.pct)
        const top = view.top_underlying ?? []
        const advs = view.advisories ?? []
        const maxThemePct = Math.max(1, ...themes.map((t: any) => t.pct))
        const maxStockPct = Math.max(1, ...top.map((s: any) => s.pct))
        const sevColor = (s: string) => s === 'high' ? '#ef4444' : s === 'medium' ? '#f59e0b' : '#22c55e'
        if (!themes.length) return <div style={{ color: 'var(--text3)', fontSize: 12, padding: 20 }}>No look-through computed yet — run <code>scripts/portfolio_lookthrough_themes.py --grok</code>.</div>
        const ltAccts = Object.keys(acctDetail)
        return (
          <div>
            <AskAgents />
            {ltAccts.length > 1 && (
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 9 }}>
                <button onClick={() => setAcctFilter(null)} style={{ fontSize: 10, padding: '3px 11px', borderRadius: 12, cursor: 'pointer', border: `1px solid ${acctFilter === null ? '#60a5fa' : 'var(--border)'}`, background: acctFilter === null ? 'rgba(96,165,250,.15)' : 'var(--bg2)', color: acctFilter === null ? '#60a5fa' : 'var(--text3)', fontWeight: acctFilter === null ? 700 : 400 }}>All accounts</button>
                {ltAccts.map(a => (
                  <button key={a} onClick={() => setAcctFilter(a === acctFilter ? null : a)} style={{ fontSize: 10, padding: '3px 11px', borderRadius: 12, cursor: 'pointer', border: `1px solid ${acctFilter === a ? acctColor(a) : 'var(--border)'}`, background: acctFilter === a ? `${acctColor(a)}22` : 'var(--bg2)', color: acctFilter === a ? acctColor(a) : 'var(--text3)', fontWeight: acctFilter === a ? 700 : 400 }}>{a.replace(/_/g, ' ')}</button>
                ))}
              </div>
            )}
            <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 10 }}>
              True stock-level look-through{acctFilter ? <b style={{ color: 'var(--text1)' }}> · {acctFilter.replace(/_/g, ' ')} (${Math.round(view.portfolio_total ?? 0).toLocaleString()})</b> : ' — funds resolved to their underlying holdings'}. Coverage <b style={{ color: 'var(--text1)' }}>{view.coverage_pct}%</b> (top-10 fund holdings; theme %s are lower bounds). Hover a stock to see which funds hold it.
            </div>
            {lt.grok_narrative && (
              <div style={{ background: 'rgba(168,85,247,.08)', border: '1px solid rgba(168,85,247,.3)', borderRadius: 10, padding: '10px 13px', marginBottom: 10 }}>
                <div style={{ fontSize: 10, fontWeight: 800, color: '#c084fc', marginBottom: 4 }}>🧠 AI ADVISORY (Grok)</div>
                <div style={{ fontSize: 11.5, color: 'var(--text1)', lineHeight: 1.55 }}>{lt.grok_narrative}</div>
              </div>
            )}
            {(view.theme_gaps ?? lt.theme_gaps ?? []).length > 0 && (() => {
              const gaps = view.theme_gaps ?? lt.theme_gaps ?? []
              const ds = gapDesign?.design
              return (
                <div style={{ background: 'rgba(34,197,94,.06)', border: '1px solid rgba(34,197,94,.3)', borderRadius: 10, padding: '11px 13px', marginBottom: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                    <div style={{ fontSize: 12, fontWeight: 800, color: '#34d399' }}>🎯 Diversification gaps — fill suggestions</div>
                    <span style={{ fontSize: 9.5, color: 'var(--text3)' }}>{gaps.length} underweight/0% sleeve{gaps.length === 1 ? '' : 's'} with a long-ETF candidate · advisory only</span>
                    <span style={{ flex: 1 }} />
                    <button disabled={gapBusy} onClick={designFill} style={{ fontSize: 10.5, fontWeight: 700, padding: '5px 12px', borderRadius: 7, border: '1px solid #a855f7', background: gapBusy ? 'var(--bg2)' : 'rgba(168,85,247,.18)', color: '#c084fc', cursor: gapBusy ? 'wait' : 'pointer' }}>{gapBusy ? 'designing…' : '🤖 Design fill plan (AI)'}</button>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 8 }}>
                    {gaps.map((g: any, i: number) => (
                      <div key={i} style={{ background: 'var(--bg2)', border: `1px solid ${g.severity === 'high' ? '#ef4444' : '#f59e0b'}44`, borderRadius: 8, padding: '8px 10px' }}>
                        <div style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text0)' }}>{g.theme} <span style={{ color: g.severity === 'high' ? '#ef4444' : '#f59e0b' }}>{g.current_pct}%</span> <span style={{ color: 'var(--text3)' }}>→ {g.target_pct}%</span></div>
                        <div style={{ fontSize: 9.5, color: 'var(--text3)', marginBottom: 6 }}>gap ≈ ${Math.round(g.gap_dollars).toLocaleString()}</div>
                        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                          {(g.suggested_etfs ?? []).map((e: any) => (
                            <button key={e.symbol} onClick={() => proposeGapEtf(e.symbol, g.theme, `Fill ${g.theme} gap (${g.current_pct}%→${g.target_pct}%) — advisory ETF candidate`)} title={`${e.name} — propose a PENDING review (no execution)`} style={{ fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 6, border: '1px solid #22c55e66', background: 'rgba(34,197,94,.12)', color: '#86efac', cursor: 'pointer' }}>{e.symbol}{gapPropose[e.symbol] ? ` · ${gapPropose[e.symbol]}` : ' + propose'}</button>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                  {gapDesign && (
                    <div style={{ marginTop: 10, borderTop: '1px solid rgba(148,163,184,.18)', paddingTop: 8 }}>
                      {ds?.summary && <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5, marginBottom: 6 }}><b style={{ color: '#c084fc' }}>AI design ({gapDesign.lane}):</b> {ds.summary}</div>}
                      {(ds?.steps ?? []).map((s: any, i: number) => (
                        <div key={i} style={{ fontSize: 10.5, color: 'var(--text2)', display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 3 }}>
                          <span style={{ fontFamily: 'monospace', fontWeight: 700, color: '#34d399' }}>{s.action} {s.symbol}</span>
                          <span>${Number(s.dollars || 0).toLocaleString()}</span>
                          <span style={{ color: 'var(--text3)' }}>· {s.funded_by}</span>
                          <span style={{ color: 'var(--text3)' }}>— {s.rationale}</span>
                          {s.symbol && <button onClick={() => proposeGapEtf(s.symbol, s.theme || '', s.rationale || 'AI fill design')} style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 5, border: '1px solid #22c55e66', background: 'rgba(34,197,94,.12)', color: '#86efac', cursor: 'pointer' }}>{gapPropose[s.symbol] || '+ propose'}</button>}
                        </div>
                      ))}
                      {ds?.parse_error && <div style={{ fontSize: 10, color: '#f59e0b' }}>AI returned unstructured text: {ds.raw}</div>}
                      {gapDesign.ok === false && <div style={{ fontSize: 10, color: '#ef4444' }}>{gapDesign.error}</div>}
                      <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 5 }}>Proposing creates a PENDING review item — manual approval + all gates still required. Nothing is executed.</div>
                    </div>
                  )}
                </div>
              )
            })()}
            {(lt.agent_advisories ?? []).length > 0 && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 8, marginBottom: 12 }}>
                {lt.agent_advisories.map((a: any, i: number) => {
                  const c = a.agent.startsWith('CIO') ? '#60a5fa' : a.agent.startsWith('Risk') ? '#ef4444' : '#22c55e'
                  return (
                    <div key={i} style={{ background: 'var(--bg2)', border: `1px solid ${c}44`, borderTop: `2px solid ${c}`, borderRadius: 8, padding: '9px 11px' }}>
                      <div style={{ fontSize: 10, fontWeight: 800, color: c, marginBottom: 4 }}>{a.agent} <span style={{ color: 'var(--text4)', fontWeight: 500 }}>· {a.model}</span></div>
                      <div style={{ fontSize: 11, color: 'var(--text1)', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{a.text}</div>
                    </div>
                  )
                })}
              </div>
            )}
            {advs.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14 }}>
                {advs.map((a: any, i: number) => (
                  <div key={i} style={{ display: 'flex', gap: 9, alignItems: 'baseline', padding: '7px 11px', borderRadius: 8, background: 'var(--bg2)', borderLeft: `3px solid ${sevColor(a.severity)}` }}>
                    <span style={{ fontSize: 8.5, fontWeight: 900, color: sevColor(a.severity), textTransform: 'uppercase' }}>{a.severity}</span>
                    <span style={{ fontSize: 11.5, fontWeight: 700, color: 'var(--text0)' }}>{a.title}</span>
                    <span style={{ fontSize: 10.5, color: 'var(--text2)' }}>{a.detail}</span>
                  </div>
                ))}
              </div>
            )}
            {top.length > 0 && (() => {
              const donut = top.slice(0, 10).map((s: any) => ({ name: s.symbol, value: s.value }))
              return (
                <div style={{ display: 'flex', gap: 16, alignItems: 'center', marginBottom: 14, background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 12 }}>
                  <div style={{ width: 190, height: 170, flexShrink: 0 }}>
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie data={donut} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={42} outerRadius={78} stroke="var(--bg0)" strokeWidth={2}>
                          {donut.map((_: any, i: number) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                        </Pie>
                        <Tooltip formatter={(v: any) => `$${Math.round(v).toLocaleString()}`} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 6 }}>Top-10 underlying concentration (look-through)</div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px' }}>
                      {donut.map((d: any, i: number) => (
                        <span key={d.name} style={{ fontSize: 10.5, color: 'var(--text2)' }}>
                          <span style={{ color: COLORS[i % COLORS.length] }}>●</span> <b style={{ color: 'var(--text1)' }}>{d.name}</b> ${(d.value / 1000).toFixed(0)}k
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              )
            })()}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18 }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Theme exposure</div>
                {themes.map((t: any) => (
                  <div key={t.name} title={(t.by_stock ?? []).map((s: any) => `${s.symbol} $${Math.round(s.value).toLocaleString()}`).join(' · ')} style={{ marginBottom: 7, cursor: 'help' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
                      <span style={{ color: 'var(--text1)' }}>{t.name}</span>
                      <span style={{ color: 'var(--text2)' }}>${Math.round(t.value).toLocaleString()} · <b style={{ color: '#60a5fa' }}>{t.pct}%</b></span>
                    </div>
                    <div style={{ height: 6, background: 'var(--bg2)', borderRadius: 3, marginTop: 2 }}>
                      <div style={{ height: '100%', width: `${t.pct / maxThemePct * 100}%`, background: '#60a5fa', borderRadius: 3 }} />
                    </div>
                  </div>
                ))}
              </div>
              <div>
                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Top underlying stocks (look-through)</div>
                {top.slice(0, 15).map((s: any) => (
                  <div key={s.symbol} title={'Held via:\n' + (s.in ?? []).map((x: any) => `  ${x.src} — $${Math.round(x.value).toLocaleString()}`).join('\n')} style={{ marginBottom: 6, cursor: 'help' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
                      <span style={{ fontFamily: 'monospace', color: 'var(--text1)' }}>{s.symbol} <span style={{ fontSize: 8.5, color: 'var(--text4)' }}>ⓘ</span></span>
                      <span style={{ color: 'var(--text2)' }}>${Math.round(s.value).toLocaleString()} · <b style={{ color: s.pct >= 8 ? '#ef4444' : s.pct >= 5 ? '#f59e0b' : '#22c55e' }}>{s.pct}%</b></span>
                    </div>
                    <div style={{ height: 6, background: 'var(--bg2)', borderRadius: 3, marginTop: 2 }}>
                      <div style={{ height: '100%', width: `${s.pct / maxStockPct * 100}%`, background: s.pct >= 8 ? '#ef4444' : s.pct >= 5 ? '#f59e0b' : '#22c55e', borderRadius: 3 }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )
      })()}

      {tab === 'Dividends' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Dividend Income</div>
          {divs ? (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 16 }}>
                <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 10, textAlign: 'center' }}>
                  <div style={{ fontSize: 18, fontWeight: 700, color: '#22c55e' }}>{fmt$(divs.total_annual ?? 0, 0)}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>Annual</div>
                </div>
                <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 10, textAlign: 'center' }}>
                  <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)' }}>{fmt$(divs.monthly_average ?? 0, 0)}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>Monthly Avg</div>
                </div>
                <div style={{ background: 'var(--bg2)', borderRadius: 8, padding: 10, textAlign: 'center' }}>
                  <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)' }}>{payers.length}</div>
                  <div style={{ fontSize: 9, color: 'var(--text3)' }}>Payers</div>
                </div>
              </div>
              <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/dividends</div>
            </>
          ) : <div style={{ color: 'var(--text3)', fontSize: 11 }}>Loading dividend data...</div>}
        </div>
      )}

      {tab === 'Returns' && perfData && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Portfolio Performance</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text0)', marginBottom: 12 }}>{fmt$(perfData.current_value ?? 0, 0)}</div>
            {(perfData.max_drawdown_pct_30d ?? perfData.max_drawdown_pct) != null && (
              <div style={{ fontSize: 10, color: '#ef4444', marginBottom: 10 }}>
                Max drawdown (30d) <b>{(perfData.max_drawdown_pct_30d ?? perfData.max_drawdown_pct).toFixed(1)}%</b>
                {perfData.max_drawdown_pct_30d != null && perfData.max_drawdown_pct != null
                  && perfData.max_drawdown_pct_30d !== perfData.max_drawdown_pct && (
                  <span style={{ fontSize: 8, color: 'var(--text4)', marginLeft: 6 }}>
                    all-time {perfData.max_drawdown_pct.toFixed(1)}%
                  </span>
                )}
              </div>
            )}
            {perfData.periods && Object.entries(perfData.periods).map(([period, data]: [string, any]) => {
              const src = data?.source === 'market_day' ? 'market' : (data?.estimated ? 'est.' : (data?.source ?? ''))
              return (
              <div key={period} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 6px', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
                <span style={{ color: 'var(--text2)' }}>
                  {period}
                  {period === '1D' && src === 'market' && <span style={{ fontSize: 8, color: 'var(--text4)', marginLeft: 4 }}>market day</span>}
                  {period === '1D' && data?.snapshot_replaced && data?.snapshot_1d_pct != null && (
                    <span style={{ fontSize: 8, color: '#f59e0b', marginLeft: 4 }} title={`Snapshot-based 1D was ${data.snapshot_1d_pct}% (reconciliation correction excluded)`}>
                      was {Number(data.snapshot_1d_pct).toFixed(1)}%
                    </span>
                  )}
                </span>
                <span style={{ color: (data?.change_pct ?? 0) >= 0 ? '#22c55e' : '#ef4444' }}>
                  {data?.change_pct != null ? `${data.change_pct >= 0 ? '+' : ''}${data.change_pct.toFixed(2)}%` : '—'}
                </span>
                <span style={{ color: 'var(--text2)' }}>{data?.change != null ? fmt$(data.change, 0) : '—'}</span>
              </div>
            )})}
            {perfData.snapshot_outliers?.length > 0 && (
              <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 8 }}>
                Drawdown excludes {perfData.snapshot_outliers.length} reconciliation outlier snapshot{perfData.snapshot_outliers.length > 1 ? 's' : ''} ({perfData.snapshot_outliers.slice(-2).join(', ')}).
              </div>
            )}
            {perfData.warning && <div style={{ fontSize: 9, color: '#f59e0b', marginTop: 8 }}>{perfData.warning}</div>}
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/portfolio/performance</div>
          </div>

          {(perfData.drawdown_series?.length > 1) && (
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
              <DrawdownChart
                title="Portfolio underwater / drawdown"
                data={perfData.drawdown_series.map((p: any) => ({
                  date: String(p.date || '').slice(5) || p.date,
                  drawdown: Number(p.drawdown ?? 0),
                  value: Number(p.value ?? 0),
                }))}
                valueKey="drawdown"
              />
            </div>
          )}

          {(riskData?.positions?.length > 0) && (
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
              <RiskContributionBars
                positions={riskData.positions}
                title="Risk contribution (max loss)"
                mode="risk"
                height={220}
              />
            </div>
          )}
        </div>
      )}
      {tab === 'Returns' && !perfData && <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20 }}>Loading performance data...</div>}
      {tab === 'Forecast' && (() => {
        const f = forecast?.data ?? forecast ?? {}
        const proj = f.projections ?? {}
        const payers = f.top_dividend_payers ?? []
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10 }}>
              {[
                { k: 'Annual dividend income', v: fmt$(f.annual_dividend_income ?? 0, 0), c: '#22c55e' },
                { k: 'Monthly avg', v: fmt$(f.monthly_dividend_avg ?? 0, 0), c: 'var(--text0)' },
                { k: 'Portfolio yield', v: `${(f.portfolio_yield_pct ?? 0).toFixed(2)}%`, c: '#60a5fa' },
                { k: 'Retirement age', v: f.retirement_age ?? '—', c: '#a855f7' },
              ].map(s => (
                <div key={s.k} style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 8px', textAlign: 'center' }}>
                  <div style={{ fontSize: 17, fontWeight: 700, color: s.c }}>{s.v}</div>
                  <div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{s.k}</div>
                </div>
              ))}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Projections (10y)</div>
                {Object.entries(proj).map(([k, v]: any) => (
                  <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid var(--border)', fontSize: 11 }}>
                    <span style={{ color: 'var(--text3)', textTransform: 'capitalize' }}>{k}</span>
                    <span style={{ color: 'var(--text0)', fontWeight: 600 }}>{typeof v === 'object' ? fmt$(v.value ?? v.projected_value ?? v.total ?? 0, 0) : (typeof v === 'number' ? fmt$(v, 0) : String(v))}</span>
                  </div>
                ))}
              </div>
              <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, maxHeight: 240, overflowY: 'auto' }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Top Dividend Payers</div>
                {payers.slice(0, 10).map((p: any, i: number) => (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '1fr auto auto', gap: 8, padding: '3px 0', borderBottom: '1px solid var(--border)', fontSize: 10, alignItems: 'center' }}>
                    <span style={{ fontFamily: 'monospace', color: 'var(--text1)' }}>{p.symbol} <ProAnalystPill symbol={p.symbol} map={paMap} compact /></span>
                    <span style={{ color: '#22c55e' }}>{Number(p.yield_pct ?? 0).toFixed(1)}%</span>
                    <span style={{ color: 'var(--text2)' }}>{fmt$(p.annual_income ?? 0, 0)}/y</span>
                  </div>
                ))}
              </div>
            </div>
            <div style={{ fontSize: 8, color: 'var(--text3)' }}>Source: /api/v2/forecast — {f.assumptions?.basis ?? 'dividend-income projection'}. {f.assumptions?.limitations ?? ''}</div>
          </div>
        )
      })()}

      {tab === 'Tax' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Tax Lots ({taxLots?.count ?? 0})</div>
          {taxLots?.harvest_candidates?.length > 0 && (
            <div style={{ marginBottom: 12, padding: '6px 10px', background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.15)', borderRadius: 6, fontSize: 11, color: '#f59e0b' }}>
              {taxLots.harvest_candidates.length} harvest candidates
            </div>
          )}
          <div style={{ fontSize: 9, color: 'var(--text3)' }}>{taxLots?.data_note ?? 'Source: /api/v2/tax-lots'}</div>
        </div>
      )}
    </div>
  )
}
