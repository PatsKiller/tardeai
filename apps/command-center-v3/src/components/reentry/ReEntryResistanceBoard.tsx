import { useEffect, useMemo, useState } from 'react'
import { BB } from '../../lib/holdingsTerminalTokens'
import { fmt$ } from '../../lib/format'

const KEY = 'portfolio.reentry.resistance.v1'

type Row = {
  state: 'ABOVE' | 'BELOW' | 'TESTING' | 'UNAVAILABLE'
  resistance: number | null
  current_close?: number | null
  distance_pct: number | null
  hold_days: number | null
  hold_start: string | null
  tests: number | null
  as_of: string | null
  method?: string
  reason?: string
}

function color(state: Row['state']): string {
  if (state === 'ABOVE') return BB.green
  if (state === 'BELOW') return BB.red
  if (state === 'TESTING') return BB.amber
  return BB.text3
}

export default function ReEntryResistanceBoard() {
  const [payload, setPayload] = useState<any>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [showAll, setShowAll] = useState(false)
  const load = () => {
    setError('')
    fetch(`/api/v2/ui/prefs/get?key=${encodeURIComponent(KEY)}`, { cache: 'no-store' })
      .then(async response => {
        const value = await response.json().catch(() => ({}))
        if (!response.ok || value?.ok === false) throw new Error(value?.error || String(response.status))
        setPayload(value?.value ?? value?.data?.value ?? null)
      })
      .catch(value => setError(String(value?.message || value)))
  }
  useEffect(load, [])
  const symbols: Record<string, Row> = payload?.symbols ?? {}
  const rows = useMemo(() => Object.entries(symbols)
    .filter(([symbol]) => !query.trim() || symbol.includes(query.trim().toUpperCase()))
    .sort(([, a], [, b]) => {
      const ar = a.distance_pct === null ? Number.POSITIVE_INFINITY : Math.abs(a.distance_pct)
      const br = b.distance_pct === null ? Number.POSITIVE_INFINITY : Math.abs(b.distance_pct)
      return ar - br
    }), [symbols, query])
  const shown = rows.slice(0, showAll ? rows.length : 30)
  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 8, padding: 10 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 900 }}>RESISTANCE / RECLAIM BOARD</div>
          <div style={{ fontSize: 10, color: BB.text3 }}>Closed sessions only · nearest resistance first · intraday crosses never count as a hold</div>
        </div>
        <div style={{ marginLeft: 'auto', fontSize: 10, color: BB.text3 }}>generated {payload?.generated_at ? String(payload.generated_at).slice(0, 19).replace('T', ' ') : 'not available'} · {payload?.symbol_count ?? rows.length} symbols</div>
      </div>
      <div style={{ display: 'flex', gap: 7, marginTop: 8 }}>
        <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Filter resistance symbols…" style={{ minWidth: 220, fontSize: 11, padding: '5px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)' }} />
        <button onClick={load} style={{ fontSize: 10.5, fontWeight: 800, padding: '5px 9px', borderRadius: 5, cursor: 'pointer', border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)' }}>REFRESH</button>
        <button onClick={() => setShowAll(value => !value)} style={{ fontSize: 10.5, fontWeight: 800, padding: '5px 9px', borderRadius: 5, cursor: 'pointer', border: `1px solid ${showAll ? BB.blue : 'var(--border)'}`, background: showAll ? BB.blueDim : 'var(--bg2)', color: showAll ? BB.blue : 'var(--text2)' }}>{showAll ? 'SHOW NEAREST 30' : `SHOW ALL ${rows.length}`}</button>
      </div>
      {error && <div style={{ marginTop: 7, fontSize: 10, color: BB.red }}>RESISTANCE CACHE UNAVAILABLE: {error}</div>}
      {!error && !payload && <div style={{ marginTop: 7, fontSize: 10, color: BB.text3 }}>Waiting for the scheduled Watch evaluator to publish closed-session resistance evidence.</div>}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 7, marginTop: 9 }}>
        {shown.map(([symbol, row]) => {
          const tone = color(row.state)
          const hold = row.hold_days === null ? 'hold unavailable' : row.hold_days > 0 ? `${row.hold_days} closes held` : 'not held above'
          const distance = row.distance_pct === null ? 'distance unavailable' : `${row.distance_pct >= 0 ? '+' : ''}${row.distance_pct.toFixed(1)}%`
          return (
            <div key={symbol} title={`${row.method ?? ''}${row.reason ? ` · ${row.reason}` : ''}`} style={{ minWidth: 190, background: 'var(--bg2)', border: `1px solid ${tone}`, borderRadius: 5, padding: '7px 9px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><b style={{ fontSize: 12 }}>{symbol}</b><b style={{ fontSize: 10, color: tone }}>{row.state}</b></div>
              <div style={{ fontSize: 10.5, marginTop: 3 }}>close {row.current_close == null ? '—' : fmt$(row.current_close, 2)} · resistance {row.resistance == null ? '—' : fmt$(row.resistance, 2)}</div>
              <div style={{ fontSize: 10, color: tone }}>{distance} · {hold}</div>
              <div style={{ fontSize: 10, color: BB.text3 }}>{row.hold_start ? `hold began ${row.hold_start}` : 'no active hold start'} · tests {row.tests ?? '—'} · as of {row.as_of ?? '—'}</div>
            </div>
          )
        })}
      </div>
      {payload && shown.length === 0 && <div style={{ marginTop: 8, fontSize: 10, color: BB.text3 }}>No symbols match the current filter.</div>}
    </div>
  )
}
