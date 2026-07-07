// ByTickerPanel — per-ticker AGGREGATE performance over time (the gap: the Journal grouped by day /
// strategy / account but never by symbol). Answers "aggregate total performance of a ticker over time"
// — e.g. all BJDX trades → #trades, journal win rate, total/avg P&L, avg hold, best/worst, profit factor.
// Backed by GET /api/v2/journal/by-ticker (realized closed trades). Each ticker expands to its
// per-strategy & per-account split and the individual trades. Read-only.
import { useState, useMemo, Fragment } from 'react'
import { useApi } from '../../hooks/useApi'
import { fmt$ } from '../../lib/format'

const GREEN = '#22c55e', RED = '#ef4444', MUTED = '#94a3b8', DIM = '#64748b'
const pnlColor = (n: any) => (n == null ? MUTED : Number(n) > 0 ? GREEN : Number(n) < 0 ? RED : MUTED)
const num = (n: any, d = 2) => (n == null ? '—' : Number(n).toFixed(d))
const pct = (n: any) => (n == null ? '—' : `${Number(n).toFixed(1)}%`)
const pf = (n: any) => (n == null ? '∞' : Number(n).toFixed(2)) // null PF = no losing trades

const th: React.CSSProperties = { fontSize: 9.5, fontWeight: 700, letterSpacing: '.05em', textTransform: 'uppercase', color: DIM, textAlign: 'right', padding: '6px 10px', whiteSpace: 'nowrap' }
const td: React.CSSProperties = { fontSize: 12, padding: '7px 10px', textAlign: 'right', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' }
const cell = (v: string, style: React.CSSProperties = {}) => <td style={{ ...td, ...style }}>{v}</td>

function TickerDetail({ symbol, from, to, account }: { symbol: string; from?: string; to?: string; account?: string }) {
  const qs = new URLSearchParams({ symbol })
  if (from) qs.set('from', from); if (to) qs.set('to', to); if (account) qs.set('account', account)
  const { data, loading } = useApi<any>(`/api/v2/journal/by-ticker?${qs.toString()}`, 0)
  if (loading && !data) return <div style={{ padding: 12, color: MUTED, fontSize: 11 }}>Loading {symbol}…</div>
  const byStrat: any[] = data?.by_strategy || []
  const byAcct: any[] = data?.by_account || []
  const trades: any[] = data?.trades || []
  const mini = (rows: any[], label: string, keyName: string) => (
    <div style={{ flex: 1, minWidth: 220 }}>
      <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: DIM, marginBottom: 4 }}>{label}</div>
      {rows.length === 0 && <div style={{ fontSize: 11, color: MUTED }}>—</div>}
      {rows.map((r, i) => (
        <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, padding: '2px 0' }}>
          <span style={{ color: MUTED }}>{String(r[keyName] ?? '—').replace(/_/g, ' ')}</span>
          <span style={{ fontVariantNumeric: 'tabular-nums' }}>
            <span style={{ color: DIM }}>{r.trades}t · {pct(r.win_rate_pct)} · </span>
            <span style={{ color: pnlColor(r.total_pnl) }}>{fmt$(Number(r.total_pnl), 0)}</span>
          </span>
        </div>
      ))}
    </div>
  )
  return (
    <div style={{ padding: '10px 14px', background: 'var(--bg1, rgba(2,6,23,.35))', borderTop: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', marginBottom: 10 }}>
        {mini(byStrat, 'By strategy', 'strategy')}
        {mini(byAcct, 'By account', 'account')}
      </div>
      <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: DIM, marginBottom: 4 }}>
        Individual trades ({trades.length})
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', minWidth: 560 }}>
          <thead><tr>
            {['Close', 'Acct', 'Strat', 'Shares', 'Buy', 'Sell', 'P&L', 'P&L %', 'Hold', 'R'].map(h =>
              <th key={h} style={{ ...th, textAlign: h === 'Acct' || h === 'Strat' ? 'left' : 'right' }}>{h}</th>)}
          </tr></thead>
          <tbody>
            {trades.map((t, i) => (
              <tr key={i} style={{ borderTop: '1px solid var(--border)' }}>
                {cell(String(t.close_date || '').slice(0, 10), { textAlign: 'left', color: MUTED })}
                {cell(String(t.account || '').replace(/_/g, ' '), { textAlign: 'left', color: MUTED, fontSize: 10.5 })}
                {cell(String(t.strategy || '—').replace(/_/g, ' '), { textAlign: 'left', color: MUTED, fontSize: 10.5 })}
                {cell(num(t.shares, 0))}
                {cell(fmt$(Number(t.buy_price), 2))}
                {cell(fmt$(Number(t.sell_price), 2))}
                {cell(fmt$(Number(t.pnl), 2), { color: pnlColor(t.pnl), fontWeight: 700 })}
                {cell(pct(t.pnl_pct), { color: pnlColor(t.pnl_pct) })}
                {cell(t.hold_days == null ? '—' : `${num(t.hold_days, 0)}d`)}
                {cell(num(t.r_multiple, 2))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function HoldChart({ dist }: { dist: any[] }) {
  const [mode, setMode] = useState<'trades' | 'pnl'>('trades')
  if (!dist || dist.length === 0) return null
  // API Decimals serialize as strings → coerce to numbers.
  const data = dist.map(d => ({
    bucket: String(d.bucket),
    trades: Number(d.trades) || 0,
    total_pnl: Number(d.total_pnl) || 0,
    win_rate_pct: Number(d.win_rate_pct) || 0,
    avg_pnl: Number(d.avg_pnl) || 0,
    avg_hold_days: Number(d.avg_hold_days) || 0,
  }))
  const key: 'trades' | 'total_pnl' = mode === 'pnl' ? 'total_pnl' : 'trades'
  const maxAbs = Math.max(1, ...data.map(d => Math.abs(d[key])))
  const CHART_H = 130
  const btn = (m: 'trades' | 'pnl', label: string) => (
    <button onClick={() => setMode(m)} style={{
      fontSize: 10, fontWeight: 700, padding: '3px 9px', borderRadius: 6, cursor: 'pointer',
      border: `1px solid ${mode === m ? '#60a5fa' : 'var(--border)'}`,
      background: mode === m ? 'rgba(96,165,250,.14)' : 'transparent', color: mode === m ? '#60a5fa' : MUTED,
    }}>{label}</button>
  )
  // Pure HTML/CSS bars — NO SVG / recharts — so they render identically in every browser (no SVG/GPU quirks).
  return (
    <div style={{ marginBottom: 12, padding: '10px 14px', background: 'var(--bg2)', borderRadius: 8, border: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, fontWeight: 800 }}>Performance by holding period</span>
        <span style={{ fontSize: 10, color: MUTED }}>intraday → long · green when the band is net-profitable</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>{btn('trades', '# Trades')}{btn('pnl', 'Total P&L')}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 10, height: CHART_H }}>
        {data.map((d, i) => {
          const val = d[key]
          const barH = Math.max(3, Math.round(Math.abs(val) / maxAbs * (CHART_H - 22)))
          const color = d.total_pnl > 0 ? GREEN : d.total_pnl < 0 ? RED : MUTED
          const label = mode === 'pnl' ? (Math.abs(val) >= 1000 ? `$${(val / 1000).toFixed(0)}k` : fmt$(val, 0)) : String(val)
          const title = `${d.bucket} · avg ${num(d.avg_hold_days, 1)}d hold\n${d.trades} trades · ${pct(d.win_rate_pct)} win\nTotal P&L ${fmt$(d.total_pnl, 0)} · avg ${fmt$(d.avg_pnl, 0)}`
          return (
            <div key={i} title={title} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end', height: '100%' }}>
              <div style={{ fontSize: 9.5, fontWeight: 700, color: MUTED, marginBottom: 3, fontVariantNumeric: 'tabular-nums' }}>{label}</div>
              <div style={{ width: '68%', maxWidth: 90, height: barH, background: color, borderRadius: '3px 3px 0 0' }} />
            </div>
          )
        })}
      </div>
      <div style={{ display: 'flex', gap: 10, marginTop: 5, borderTop: '1px solid var(--border)', paddingTop: 4 }}>
        {data.map((d, i) => (
          <div key={i} style={{ flex: 1, textAlign: 'center', fontSize: 10, color: MUTED }}>{d.bucket}</div>
        ))}
      </div>
    </div>
  )
}

export default function ByTickerPanel({ account, from, to }: { account?: string; from?: string; to?: string }) {
  const [open, setOpen] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const qs = new URLSearchParams()
  if (from) qs.set('from', from); if (to) qs.set('to', to); if (account) qs.set('account', account)
  const { data, loading, error } = useApi<any>(`/api/v2/journal/by-ticker?${qs.toString()}`, 120_000)
  const tickers: any[] = data?.tickers || []
  const totals = data?.totals || {}
  const holdDist: any[] = data?.hold_distribution || []
  const shown = useMemo(() => {
    const s = search.trim().toUpperCase()
    return s ? tickers.filter(t => String(t.symbol).toUpperCase().includes(s)) : tickers
  }, [tickers, search])

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 800 }}>Performance by Ticker</div>
        <span style={{ fontSize: 10.5, color: MUTED }}>realized closed trades{from ? ` · since ${String(from).slice(0, 10)}` : ' · all time'}{account ? ` · ${account.replace(/_/g, ' ')}` : ''}</span>
        <input
          value={search} onChange={e => setSearch(e.target.value)} placeholder="filter symbol (e.g. BJDX)"
          style={{ marginLeft: 'auto', fontSize: 11, padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text)' }}
        />
      </div>

      {/* totals */}
      <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginBottom: 12, padding: '10px 14px', background: 'var(--bg2)', borderRadius: 8, border: '1px solid var(--border)' }}>
        {[['Symbols', String(tickers.length)], ['Trades', String(totals.trades ?? '—')],
          ['Win rate', pct(totals.win_rate_pct)], ['Total P&L', fmt$(Number(totals.total_pnl || 0), 0)],
          ['Avg P&L', fmt$(Number(totals.avg_pnl || 0), 0)], ['Avg hold', totals.avg_hold_days == null ? '—' : `${num(totals.avg_hold_days, 1)}d`],
          ['Profit factor', pf(totals.profit_factor)]].map(([k, v]) => (
          <div key={k} style={{ display: 'flex', flexDirection: 'column' }}>
            <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '.06em', textTransform: 'uppercase', color: DIM }}>{k}</span>
            <span style={{ fontSize: 15, fontWeight: 800, fontVariantNumeric: 'tabular-nums', color: k === 'Total P&L' || k === 'Avg P&L' ? pnlColor(k === 'Total P&L' ? totals.total_pnl : totals.avg_pnl) : 'var(--text)' }}>{v}</span>
          </div>
        ))}
      </div>

      {/* hold-length distribution chart */}
      <HoldChart dist={holdDist} />

      {loading && tickers.length === 0 && <div style={{ color: MUTED, fontSize: 12 }}>Loading per-ticker performance…</div>}
      {error && <div style={{ color: RED, fontSize: 12 }}>Failed to load: {error}</div>}
      {!loading && tickers.length === 0 && !error && (
        <div style={{ color: MUTED, fontSize: 12 }}>No closed trades in range. (If you expected trades here and they're missing, the broker ingest may be behind — see the Schwab token status.)</div>
      )}
      {search && shown.length === 0 && tickers.length > 0 && (
        <div style={{ color: MUTED, fontSize: 12 }}>No closed trades for “{search.toUpperCase()}” in range yet.</div>
      )}

      {shown.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 720 }}>
            <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
              <th style={{ ...th, textAlign: 'left' }}>Symbol</th>
              {['Trades', 'Win %', 'Total P&L', 'Avg P&L', 'Avg P&L %', 'Avg Hold', 'Best', 'Worst', 'PF', 'Last'].map(h => <th key={h} style={th}>{h}</th>)}
            </tr></thead>
            <tbody>
              {shown.map(t => (
                <Fragment key={t.symbol}>
                  <tr onClick={() => setOpen(o => o === t.symbol ? null : t.symbol)}
                    style={{ borderTop: '1px solid var(--border)', cursor: 'pointer', background: open === t.symbol ? 'var(--bg2)' : 'transparent' }}>
                    <td style={{ ...td, textAlign: 'left', fontWeight: 800, fontSize: 13 }}>
                      <span style={{ color: DIM, marginRight: 6 }}>{open === t.symbol ? '▾' : '▸'}</span>{t.symbol}
                    </td>
                    {cell(String(t.trades))}
                    {cell(pct(t.win_rate_pct), { color: Number(t.win_rate_pct) >= 50 ? GREEN : Number(t.win_rate_pct) > 0 ? RED : MUTED })}
                    {cell(fmt$(Number(t.total_pnl), 0), { color: pnlColor(t.total_pnl), fontWeight: 700 })}
                    {cell(fmt$(Number(t.avg_pnl), 0), { color: pnlColor(t.avg_pnl) })}
                    {cell(pct(t.avg_pnl_pct), { color: pnlColor(t.avg_pnl_pct) })}
                    {cell(t.avg_hold_days == null ? '—' : `${num(t.avg_hold_days, 1)}d`)}
                    {cell(fmt$(Number(t.best_pnl), 0), { color: GREEN })}
                    {cell(fmt$(Number(t.worst_pnl), 0), { color: Number(t.worst_pnl) < 0 ? RED : MUTED })}
                    {cell(pf(t.profit_factor))}
                    {cell(String(t.last_close || '').slice(5, 10), { color: MUTED })}
                  </tr>
                  {open === t.symbol && (
                    <tr>
                      <td colSpan={11} style={{ padding: 0 }}>
                        <TickerDetail symbol={t.symbol} from={from} to={to} account={account} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
