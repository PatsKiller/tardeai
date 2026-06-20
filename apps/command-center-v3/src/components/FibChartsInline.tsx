import { useEffect, useState } from 'react'
import { TFChart, buildFibLevels } from './FibChartModal'

// Inline daily + monthly candlestick charts (with Fib levels / swing points / confluence as price lines)
// for the detail drawer. Auto-fetches the multi-timeframe analysis for the symbol. Read-only/advisory.

export default function FibChartsInline({ symbol }: { symbol: string }) {
  const [data, setData] = useState<any>(null)
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setData(null); setErr(''); setLoading(true)
    if (!symbol || !/^[A-Za-z]{1,5}$/.test(symbol)) { setLoading(false); setErr('not chartable'); return }
    fetch(`/api/v2/symbol/fib-confluence?symbol=${encodeURIComponent(symbol)}`)
      .then(r => r.json()).then(j => { if (cancelled) return; const d = j?.data ?? j; if (d?.ok === false) setErr(d.error || 'unavailable'); else setData(d) })
      .catch(e => { if (!cancelled) setErr(e?.message || 'failed') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [symbol])

  if (err) return <div style={{ fontSize: 11, color: 'var(--text3)' }}>{err === 'not chartable' ? 'No chart for this instrument (cash / fund).' : `chart unavailable: ${err}`}</div>
  if (loading) return <div style={{ fontSize: 11, color: 'var(--text3)' }}>analyzing daily &amp; monthly charts…</div>
  if (!data?.chart_bars?.length) return <div style={{ fontSize: 11, color: 'var(--text3)' }}>no chart data</div>

  const levels = buildFibLevels(data)
  return (
    <div>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
        <TFChart label="Daily" bars={data.chart_bars} levels={levels} />
        {data.chart_bars_monthly?.length ? <TFChart label="Monthly" bars={data.chart_bars_monthly} levels={levels} /> : null}
      </div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 8 }}>
        {levels.filter(l => l.price > 0).slice(0, 24).map((l, i) => (
          <span key={i} style={{ fontSize: 9, color: l.color, display: 'flex', alignItems: 'center', gap: 4 }}><span style={{ width: 10, height: 2, background: l.color, display: 'inline-block' }} />{l.title} ${l.price}</span>
        ))}
      </div>
    </div>
  )
}
