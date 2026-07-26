import { useMemo, useState } from 'react'
import { useApi } from '../../hooks/useApi'
import { BB, T, TYPE, numStyle, heatRamp } from '../../lib/watchTokens'

// Home v2 WS-B: operator book as Finviz-style treemap.
// Freshness (2026-07-26): always show holdings.json as_of; amber lag when behind live prices.

interface Row { symbol: string; account?: string; value: number; day_change: number; day_change_pct?: number; weight_pct?: number; sector: string; stop?: string }
interface Rect { x: number; y: number; w: number; h: number; row?: Row; group?: string }

function squarify(items: { size: number; payload: any }[], x: number, y: number, w: number, h: number): { x: number; y: number; w: number; h: number; payload: any }[] {
  const out: { x: number; y: number; w: number; h: number; payload: any }[] = []
  let rest = items.filter(i => i.size > 0).sort((a, b) => b.size - a.size)
  const total = rest.reduce((s, i) => s + i.size, 0) || 1
  let area = w * h
  rest = rest.map(i => ({ ...i, size: (i.size / total) * area }))
  let cx = x, cy = y, cw = w, ch = h
  while (rest.length) {
    const strip: typeof rest = []
    const along = Math.min(cw, ch)
    let best = Infinity
    for (const it of rest) {
      strip.push(it)
      const sum = strip.reduce((s, i) => s + i.size, 0)
      const thick = sum / along
      const worst = Math.max(...strip.map(i => {
        const len = i.size / thick
        return Math.max(thick / len, len / thick)
      }))
      if (worst > best) { strip.pop(); break }
      best = worst
    }
    const sum = strip.reduce((s, i) => s + i.size, 0)
    const thick = sum / along
    let off = 0
    for (const it of strip) {
      const len = it.size / thick
      if (cw >= ch) out.push({ x: cx, y: cy + off, w: thick, h: len, payload: it.payload })
      else out.push({ x: cx + off, y: cy, w: len, h: thick, payload: it.payload })
      off += len
    }
    if (cw >= ch) { cx += thick; cw -= thick } else { cy += thick; ch -= thick }
    rest = rest.slice(strip.length)
  }
  return out
}

function ageHint(asOf?: string): string {
  if (!asOf) return ''
  const m = String(asOf).match(/(\d{4}-\d{2}-\d{2})/)
  if (!m) return ''
  const snap = new Date(`${m[1]}T12:00:00`)
  const today = new Date()
  const lag = Math.floor((today.getTime() - snap.getTime()) / 86400000)
  if (lag <= 0) return ''
  if (lag === 1) return ' · snapshot 1d behind live prices'
  return ` · snapshot ${lag}d behind live prices`
}

export default function BookTreemap({ onDrillSymbol }: { onDrillSymbol?: (symbol: string) => void }) {
  const { data } = useApi<any>('/api/v2/portfolio/book-map', 120_000)
  const [sizeBy, setSizeBy] = useState<'value' | 'impact'>('value')
  const [groupBy, setGroupBy] = useState<'sector' | 'account'>('sector')
  const [hover, setHover] = useState<Row | null>(null)
  const W = 560, H = 340, HEAD = 13

  const rects = useMemo<Rect[]>(() => {
    let rows: Row[] = data?.rows || []
    if (!rows.length) return []
    if (groupBy === 'sector') {
      const by = new Map<string, Row>()
      for (const r of rows) {
        const prev = by.get(r.symbol)
        if (prev) {
          prev.value += r.value
          prev.day_change += r.day_change
          prev.account = `${prev.account}, ${r.account}`
          if (r.stop === 'triggered' || (r.stop === 'unprotected' && prev.stop !== 'triggered')) prev.stop = r.stop
        } else by.set(r.symbol, { ...r })
      }
      rows = [...by.values()]
    }
    const groups = new Map<string, Row[]>()
    for (const r of rows) {
      const g = groupBy === 'sector' ? r.sector : (r.account || 'unknown')
      if (!groups.has(g)) groups.set(g, [])
      groups.get(g)!.push(r)
    }
    const sz = (r: Row) => sizeBy === 'value' ? r.value : Math.abs(r.day_change) || 0.01
    const gItems = [...groups.entries()].map(([g, rs]) => ({ size: rs.reduce((s, r) => s + sz(r), 0), payload: { g, rs } }))
    const gRects = squarify(gItems, 0, 0, W, H)
    const out: Rect[] = []
    for (const gr of gRects) {
      out.push({ x: gr.x, y: gr.y, w: gr.w, h: HEAD, group: gr.payload.g })
      const inner = squarify(gr.payload.rs.map((r: Row) => ({ size: sz(r), payload: r })),
        gr.x, gr.y + HEAD, gr.w, Math.max(0, gr.h - HEAD))
      for (const ir of inner) out.push({ ...ir, row: ir.payload })
    }
    return out
  }, [data, sizeBy, groupBy])

  if (!data?.ok) return <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: 14, fontSize: TYPE.sm, color: BB.text3 }}>Book map: {data?.error || 'loading…'}</div>

  const lag = ageHint(data.as_of)

  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderLeft: `3px solid ${BB.green}`, borderRadius: 2, padding: '10px 12px' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap', marginBottom: 6 }}>
        <span style={{ fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.06em', color: BB.text2 }}>YOUR BOOK</span>
        <span style={{ fontSize: 8.5, fontWeight: 700, color: lag ? BB.amber : BB.text3, textTransform: 'uppercase' }}>
          · holdings.json {String(data.as_of || '')} · ${Math.round(data.total_value).toLocaleString()} · day{' '}
          <b style={{ color: data.total_day_change >= 0 ? BB.green : BB.red }}>
            {data.total_day_change >= 0 ? '+' : ''}${Math.round(data.total_day_change).toLocaleString()}
          </b>
          {lag}
        </span>
        <span style={{ flex: 1 }} />
        {(['value', 'impact'] as const).map(m => (
          <button key={m} onClick={() => setSizeBy(m)} style={{ fontSize: 9, fontWeight: sizeBy === m ? 800 : 600, padding: '1px 7px', borderRadius: 2, cursor: 'pointer', border: `1px solid ${sizeBy === m ? T.link : BB.borderHair}`, background: sizeBy === m ? `${T.link}18` : 'transparent', color: sizeBy === m ? T.link : BB.text3 }}>{m === 'value' ? 'Value' : 'Day $ impact'}</button>
        ))}
        {(['sector', 'account'] as const).map(m => (
          <button key={m} onClick={() => setGroupBy(m)} style={{ fontSize: 9, fontWeight: groupBy === m ? 800 : 600, padding: '1px 7px', borderRadius: 2, cursor: 'pointer', border: `1px solid ${groupBy === m ? BB.amber : BB.borderHair}`, background: groupBy === m ? `${BB.amber}18` : 'transparent', color: groupBy === m ? BB.amber : BB.text3 }}>{m}</button>
        ))}
      </div>
      <div style={{ position: 'relative' }}>
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }}>
          {rects.map((r, i) => r.group ? (
            <g key={i}>
              <rect x={r.x} y={r.y} width={r.w} height={r.h} fill={BB.bg} stroke={BB.border} strokeWidth={0.5} />
              {r.w > 46 && <text x={r.x + 3} y={r.y + 9.5} fontSize={7.5} fontWeight={800} fill={BB.text3} style={{ textTransform: 'uppercase' as any }}>{r.group}</text>}
            </g>
          ) : r.row ? (
            <g key={i} onClick={() => onDrillSymbol?.(r.row!.symbol)}
               onMouseEnter={() => setHover(r.row!)} onMouseLeave={() => setHover(null)}
               style={{ cursor: 'pointer' }}>
              <rect x={r.x + 0.5} y={r.y + 0.5} width={Math.max(0, r.w - 1)} height={Math.max(0, r.h - 1)}
                    fill={heatRamp(r.row.day_change_pct)}
                    stroke={r.row.stop === 'triggered' ? BB.red : r.row.stop === 'unprotected' ? BB.amber : BB.bg}
                    strokeWidth={r.row.stop === 'triggered' || r.row.stop === 'unprotected' ? 2 : 0.75} />
              {r.w > 34 && r.h > 16 && (
                <text x={r.x + r.w / 2} y={r.y + r.h / 2} textAnchor="middle" dominantBaseline="middle"
                      fontSize={Math.min(13, Math.max(7, r.w / 6))} fontWeight={800} fill="#fff" style={{ pointerEvents: 'none' }}>
                  {r.row.symbol}
                  {r.h > 30 && <tspan x={r.x + r.w / 2} dy={11} fontSize={7.5} fontWeight={600}>
                    {r.row.day_change_pct != null ? `${Number(r.row.day_change_pct) >= 0 ? '+' : ''}${Number(r.row.day_change_pct).toFixed(2)}%` : ''}
                  </tspan>}
                </text>
              )}
            </g>
          ) : null)}
        </svg>
        {hover && (
          <div style={{ position: 'absolute', left: 8, bottom: 8, background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '6px 9px', fontSize: TYPE.xs, color: BB.text2, pointerEvents: 'none', boxShadow: '0 2px 10px rgba(0,0,0,.5)' }}>
            <b style={{ ...numStyle, color: BB.text1 }}>{hover.symbol}</b> · ${Math.round(hover.value).toLocaleString()} · {hover.weight_pct != null ? `${Number(hover.weight_pct).toFixed(1)}%` : '—'} of book
            <br />day <span style={{ color: hover.day_change >= 0 ? BB.green : BB.red }}>{hover.day_change >= 0 ? '+' : ''}${Math.round(hover.day_change).toLocaleString()}</span> · {hover.account}
            {hover.stop === 'triggered' && <span style={{ color: BB.red }}> · STOP TRIGGERED</span>}
            {hover.stop === 'unprotected' && <span style={{ color: BB.amber }}> · unprotected</span>}
          </div>
        )}
      </div>
      <div style={{ display: 'flex', gap: 10, marginTop: 6, fontSize: 8.5, color: BB.text3, alignItems: 'center', flexWrap: 'wrap' }}>
        <span>heat: −3%</span>
        {[-3, -1.5, 0, 1.5, 3].map(p => <span key={p} style={{ width: 18, height: 8, background: heatRamp(p), display: 'inline-block', borderRadius: 1 }} />)}
        <span>+3%</span>
        <span style={{ borderLeft: `2px solid ${BB.red}`, paddingLeft: 4 }}>stop triggered</span>
        <span style={{ borderLeft: `2px solid ${BB.amber}`, paddingLeft: 4 }}>unprotected ≥$10k</span>
        <span style={{ flex: 1 }} />
        <a href="/v3/portfolio" style={{ color: T.link, textDecoration: 'none', fontWeight: 700 }}>open full Portfolio →</a>
      </div>
    </div>
  )
}
