import type { CSSProperties } from 'react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import PageHeader from '../components/PageHeader'
import Card from '../components/Card'
import DetailDrawer, { DrawerSection, DrawerStat } from '../components/DetailDrawer'
import { useApi } from '../hooks/useApi'
import { fmt$, fmtPct, deltaColor } from '../lib/format'

interface Holding {
  symbol: string; name: string; account: string; market_value: number; portfolio_pct: number; price: number
  signal: string; rsi: number | null; sma20_pct: number | null; sma50_pct: number | null; sma200_pct: number | null; week52_high_pct: number | null; beta: number | null; pi_score?: number | null
}
interface HoldingsData { holdings: Holding[]; count: number }

export default function Technical() {
  const { data } = useApi<HoldingsData>('/api/v2/portfolio/holdings')
  const navigate = useNavigate()
  const [filter, setFilter] = useState<'all' | 'nearStop' | 'overbought' | 'bullish'>('all')
  const [selected, setSelected] = useState<Holding | null>(null)

  const holdings = data?.holdings ?? []
  const scored = holdings.filter(h => h.pi_score != null)
  const filtered = useMemo(() => {
    if (filter === 'nearStop') return scored.filter(h => (h.sma20_pct ?? 0) < 0 || (h.rsi ?? 50) < 45).sort((a, b) => (a.pi_score ?? 0) - (b.pi_score ?? 0))
    if (filter === 'overbought') return scored.filter(h => (h.rsi ?? 0) >= 70)
    if (filter === 'bullish') return scored.filter(h => (h.pi_score ?? 0) >= 60)
    return scored
  }, [scored, filter])
  const sorted = [...filtered].sort((a, b) => (b.pi_score ?? 0) - (a.pi_score ?? 0))
  const avgPi = sorted.length ? Math.round(sorted.reduce((s, h) => s + (h.pi_score ?? 0), 0) / sorted.length) : 0

  return (
    <>
      <PageHeader title={`Position Intelligence — ${sorted.length} Positions`} subtitle="Technical health across all holdings" />
      <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 8, padding: '4px 8px', background: 'var(--bg3)', borderRadius: 6 }}>
        PI Score = aggregate technical health (0–100). &lt;40 = Bearish/Defensive, 40–60 = Neutral, &gt;60 = Bullish. Near Stop = SMA20 below 0% or RSI &lt;45.
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(0, 1fr))', gap: 8, marginBottom: 12 }}>
        <Summary label="PI Score" value={String(avgPi)} tone={avgPi >= 60 ? 'green' : avgPi >= 40 ? 'amber' : 'red'} />
        <Summary label="Bullish" value={String(scored.filter(h => (h.pi_score ?? 0) >= 60).length)} tone="green" />
        <Summary label="Bearish" value={String(scored.filter(h => (h.pi_score ?? 0) < 45).length)} tone="red" />
        <Summary label="Above SMA200" value={String(scored.filter(h => (h.sma200_pct ?? 0) > 0).length)} tone="green" />
        <Summary label="Overbought" value={String(scored.filter(h => (h.rsi ?? 0) >= 70).length)} tone="amber" />
        <Summary label="Near Stop / Weak" value={String(scored.filter(h => (h.sma20_pct ?? 0) < 0 || (h.rsi ?? 50) < 45).length)} tone="red" />
      </div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 12, flexWrap: 'wrap' }}>
        {[
          ['all', 'All'],
          ['bullish', 'Bullish'],
          ['nearStop', 'Near Stop'],
          ['overbought', 'Overbought'],
        ].map(([k, label]) => <button key={k} onClick={() => setFilter(k as typeof filter)} style={{ padding: '6px 10px', borderRadius: 999, border: `1px solid ${filter === k ? 'var(--accent)' : 'var(--border)'}`, background: filter === k ? 'var(--accent-dim)' : 'var(--bg2)', color: filter === k ? 'var(--accent-bright)' : 'var(--text2)', cursor: 'pointer', fontSize: 10 }}>{label}</button>)}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 12 }}>
        {sorted.map(h => (
          <button key={`${h.symbol}-${h.account}`} onClick={() => setSelected(h)} style={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 14, padding: 14, textAlign: 'left', cursor: 'pointer' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start' }}>
              <div>
                <div style={{ fontFamily: 'var(--sans)', fontSize: 18, fontWeight: 800, color: 'var(--text0)' }}>{h.symbol}</div>
                <div style={{ color: 'var(--text3)', fontSize: 10 }}>{(h.portfolio_pct ?? 0).toFixed(1)}% · {h.signal || '—'} · <span style={{ fontSize: 9 }}>{h.account?.replace('schwab_', '').replace('fidelity_', '') || ''}</span></div>
              </div>
              <div style={{ width: 48, height: 48, borderRadius: 999, border: `3px solid ${piTone(h.pi_score ?? 0)}`, display: 'grid', placeItems: 'center', color: piTone(h.pi_score ?? 0), fontWeight: 800 }}>{h.pi_score}</div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6, marginTop: 12 }}>
              <Stat label="RSI" value={h.rsi != null ? h.rsi.toFixed(0) : '—'} color={h.rsi != null ? deltaColor(50 - h.rsi) : 'var(--text3)'} />
              <Stat label="SMA200" value={h.sma200_pct != null ? fmtPct(h.sma200_pct, 1) : '—'} color={deltaColor(h.sma200_pct)} />
              <Stat label="Target↑" value={h.week52_high_pct != null ? fmtPct(-h.week52_high_pct, 0) : '—'} color={deltaColor(-(h.week52_high_pct ?? 0))} />
              <Stat label="Beta" value={h.beta != null ? h.beta.toFixed(2) : '—'} />
            </div>
            <div style={{ marginTop: 12 }}>
              <div style={{ height: 8, background: 'var(--bg3)', borderRadius: 999, overflow: 'hidden' }}>
                <div style={{ width: `${Math.max(6, Math.min(100, (100 + (h.week52_high_pct ?? 0)) ))}%`, height: '100%', background: 'linear-gradient(90deg, #f0b90b, #0ecb81)' }} />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, fontSize: 9, color: 'var(--text3)' }}>
                <span title="Position within 52-week range. &gt;90% = near highs (potential resistance), &lt;30% = near lows (potential support/breakdown)">52-week range position</span>
                <span style={{ color: (() => { const p = Math.max(0, 100 + (h.week52_high_pct ?? 0)); return p > 90 ? 'var(--green)' : p < 30 ? 'var(--red)' : 'var(--text2)' })() }}>
                  {h.week52_high_pct != null ? `${Math.max(0, 100 + h.week52_high_pct).toFixed(0)}%` : '—'}
                </span>
              </div>
            </div>
          </button>
        ))}
      </div>
      <DetailDrawer open={!!selected} onClose={() => setSelected(null)} title={selected?.symbol || ''} subtitle="Technical / PI detail">
        {selected && (
          <>
            <DrawerSection title="Position Intelligence">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                <DrawerStat label="PI Score" value={String(selected.pi_score ?? '—')} color={piTone(selected.pi_score ?? 0)} />
                <DrawerStat label="Signal" value={selected.signal || '—'} />
                <DrawerStat label="Price" value={fmt$(selected.price, 2)} />
                <DrawerStat label="Weight" value={`${selected.portfolio_pct.toFixed(1)}%`} />
                <DrawerStat label="RSI" value={selected.rsi != null ? selected.rsi.toFixed(1) : '—'} color={selected.rsi != null ? deltaColor(50 - selected.rsi) : undefined} />
                <DrawerStat label="Beta" value={selected.beta != null ? selected.beta.toFixed(2) : '—'} />
                <DrawerStat label="SMA20" value={selected.sma20_pct != null ? fmtPct(selected.sma20_pct, 1) : '—'} color={deltaColor(selected.sma20_pct)} />
                <DrawerStat label="SMA50" value={selected.sma50_pct != null ? fmtPct(selected.sma50_pct, 1) : '—'} color={deltaColor(selected.sma50_pct)} />
                <DrawerStat label="SMA200" value={selected.sma200_pct != null ? fmtPct(selected.sma200_pct, 1) : '—'} color={deltaColor(selected.sma200_pct)} />
                <DrawerStat label="52W from High" value={selected.week52_high_pct != null ? fmtPct(selected.week52_high_pct, 1) : '—'} color={deltaColor(selected.week52_high_pct)} />
              </div>
            </DrawerSection>
            <DrawerSection title="Drillthrough">
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <button onClick={() => navigate(`/portfolio?symbol=${selected.symbol}`)} style={{ ...linkBtn, background: 'var(--bg3)', border: '1px solid var(--border)', color: 'var(--text1)', cursor: 'pointer' }}>Holdings</button>
                <button onClick={() => navigate(`/risk?symbol=${selected.symbol}`)} style={{ ...linkBtn, background: 'var(--bg3)', border: '1px solid var(--border)', color: 'var(--text1)', cursor: 'pointer' }}>Risk</button>
                <button onClick={() => navigate(`/research?symbol=${selected.symbol}`)} style={{ ...linkBtn, background: 'var(--bg3)', border: '1px solid var(--border)', color: 'var(--text1)', cursor: 'pointer' }}>Research</button>
                <a href={`https://finviz.com/quote.ashx?t=${selected.symbol}`} target="_blank" rel="noreferrer" style={linkBtn}>Finviz</a>
                <a href={`https://finance.yahoo.com/quote/${selected.symbol}`} target="_blank" rel="noreferrer" style={linkBtn}>Yahoo</a>
              </div>
            </DrawerSection>
          </>
        )}
      </DetailDrawer>
    </>
  )
}

function Summary({ label, value, tone }: { label: string; value: string; tone: 'green' | 'red' | 'amber' }) {
  const color = tone === 'green' ? 'var(--green)' : tone === 'red' ? 'var(--red)' : 'var(--amber)'
  return <Card compact><div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase' }}>{label}</div><div style={{ fontSize: 24, fontWeight: 800, color }}>{value}</div></Card>
}
function Stat({ label, value, color = 'var(--text1)' }: { label: string; value: string; color?: string }) {
  return <div><div style={{ fontSize: 8, color: 'var(--text3)', textTransform: 'uppercase' }}>{label}</div><div style={{ fontSize: 12, fontWeight: 700, color }}>{value}</div></div>
}
function piTone(score: number) {
  return score >= 65 ? 'var(--green)' : score >= 50 ? 'var(--amber)' : 'var(--red)'
}
const linkBtn: CSSProperties = { fontSize: 10, padding: '5px 10px', border: '1px solid var(--accent)', borderRadius: 999, color: 'var(--accent)', textDecoration: 'none' }
