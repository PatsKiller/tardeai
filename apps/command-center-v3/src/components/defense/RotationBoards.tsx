import { useMemo, useState } from 'react'
import { BB, T, DASH, numStyle, heatRamp } from '../../lib/watchTokens'
import { rankWithinScope, boardCallout } from '../../lib/chipScope.mjs'

// Defense v3 WS-T — the rotation picture: RRG scatter (full sector names, W/M/Q axis
// toggle) + leaders/laggards boards for sectors AND industries at W (5d) / M (20d) /
// Q (60d), with movement chips (rank at this timeframe vs the next-longer one) so
// rotation reads as MOVEMENT, not a snapshot.

const STATE_COLOR: Record<string, string> = {
  LEADING: BB.green, WEAKENING: BB.amber, LAGGING: BB.red, IMPROVING: T.link,
}
export type Timeframe = 'W' | 'M' | 'Q'

function pct(v: number | null | undefined): string {
  return v == null ? '—' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(1)}%`
}

type Dot = { key: string; label: string; x: number; y: number; book: number; state: string | null }

function Scatter({ dots, xLabel, yLabel, xMax, yMax }: { dots: Dot[]; xLabel: string; yLabel: string; xMax: number; yMax: number }) {
  const W = 560, H = 340, M = 30
  const sx = (v: number) => M + ((Math.max(-xMax, Math.min(xMax, v)) + xMax) / (2 * xMax)) * (W - 2 * M)
  const sy = (v: number) => H - M - ((Math.max(-yMax, Math.min(yMax, v)) + yMax) / (2 * yMax)) * (H - 2 * M)
  const cx = sx(0), cy = sy(0)
  const quads: Array<[number, number, number, number, string, string, number, number, string]> = [
    [cx, M, W - M - cx, cy - M, BB.green, 'LEADING', W - M - 4, M + 13, 'end'],
    [cx, cy, W - M - cx, H - M - cy, BB.amber, 'WEAKENING', W - M - 4, H - M - 6, 'end'],
    [M, M, cx - M, cy - M, T.link, 'IMPROVING', M + 4, M + 13, 'start'],
    [M, cy, cx - M, H - M - cy, BB.red, 'LAGGING', M + 4, H - M - 6, 'start'],
  ]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', display: 'block' }}>
      {quads.map(([x, y, w, h, color, name, tx, ty, anchor]) => (
        <g key={name}>
          <rect x={x} y={y} width={w} height={h} fill={color} opacity={0.07} />
          <text x={tx} y={ty} fill={color} opacity={0.8} fontSize={DASH.chip} fontWeight={800} textAnchor={anchor as any} letterSpacing=".08em">{name}</text>
        </g>
      ))}
      <line x1={cx} y1={M} x2={cx} y2={H - M} stroke={BB.border} strokeWidth={1} />
      <line x1={M} y1={cy} x2={W - M} y2={cy} stroke={BB.border} strokeWidth={1} />
      <text x={W - M} y={cy - 6} fill={BB.text3} fontSize={DASH.chip} textAnchor="end">{xLabel} →</text>
      <text x={cx + 6} y={M + 12} fill={BB.text3} fontSize={DASH.chip}>{yLabel} ↑</text>
      {dots.map((d, i) => {
        const r = Math.max(5, 4 + Math.sqrt(Math.max(0, d.book)) * 2.6)
        const c = STATE_COLOR[d.state || ''] || BB.text3
        const px = sx(d.x), py = sy(d.y)
        // labels flip below/left near edges so clamped dots don't pile text off-canvas;
        // stagger vertically when several dots clamp to the same edge band
        const below = py < M + 26
        const left = px > W - M - 90
        const ly = below ? py + r + 9 + (i % 3) * 10 : py + 4
        return (
          <g key={d.key}>
            <circle cx={px} cy={py} r={r} fill={c} opacity={0.85} stroke={BB.bg} strokeWidth={1}>
              <title>{`${d.label} — ${xLabel} ${d.x.toFixed(1)} · ${yLabel} ${d.y.toFixed(1)}${d.book ? ` · book ${d.book}%` : ''}`}</title>
            </circle>
            <text x={left ? px - r - 4 : px + r + 4} y={ly} fill={BB.text2} fontSize={DASH.chip + 1} fontWeight={700} textAnchor={left ? 'end' : 'start'}>{d.label}</text>
          </g>
        )
      })}
    </svg>
  )
}

function Board({ title, rows, tf }: { title: string; rows: Array<{ name: string; value: number | null; prevValue: number | null; state: string | null; book: number }>; tf: Timeframe }) {
  // v4: ranks + movement computed WITHIN LIST SCOPE (lib/chipScope, unit-tested);
  // callout separates the strongest IMPROVEMENT from the sharpest DETERIORATION.
  const ranked = rankWithinScope(rows as any) as any[]
  const longer = tf === 'W' ? 'M' : tf === 'M' ? 'Q' : 'M'
  const line = boardCallout(ranked, tf, longer)
  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: DASH.section, fontWeight: 800, color: BB.text2, marginBottom: 4 }}>{title}</div>
      {ranked.map((r: any) => (
        <div key={r.name} style={{ display: 'grid', gridTemplateColumns: '22px 1fr 64px 44px 56px', gap: 6, alignItems: 'center', fontSize: DASH.data, padding: '2px 0', borderBottom: `1px solid ${BB.borderHair}` }}>
          <span style={{ ...numStyle, color: BB.text3 }}>{r.rank}</span>
          <span style={{ color: BB.text1, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', borderLeft: `3px solid ${STATE_COLOR[r.state || ''] || BB.borderHair}`, paddingLeft: 6 }}>
            {r.isNew && <span title={`new to this list on ${tf}`} style={{ color: T.link }}>● </span>}{r.name}
          </span>
          <span style={{ ...numStyle, textAlign: 'right', background: heatRamp((r.value as number) / 3), color: BB.text0, borderRadius: 2, padding: '0 4px', fontWeight: 700 }}>{pct(r.value)}</span>
          <span style={{ ...numStyle, textAlign: 'right', fontSize: DASH.chip + 1 }}>
            {r.delta == null ? (r.isNew ? <span style={{ color: T.link }}>new</span> : <span style={{ color: BB.text3 }}>—</span>)
              : r.delta === 0 ? <span style={{ color: BB.text3 }}>=</span>
                : <span style={{ color: r.delta > 0 ? BB.green : BB.red }}>{r.delta > 0 ? '▲' : '▼'}{Math.abs(r.delta)}</span>}
          </span>
          <span style={{ height: 6, background: BB.borderHair, borderRadius: 1, overflow: 'hidden' }}>
            <span style={{ display: 'block', height: '100%', width: `${Math.min(100, r.book * 4)}%`, background: BB.amber }} />
          </span>
        </div>
      ))}
      <div style={{ fontSize: DASH.data, color: BB.text3, marginTop: 4 }}>{line}</div>
    </div>
  )
}

export default function RotationBoards({ sectors, industries, spyLong }: { sectors: any[]; industries: any[]; spyLong: number | null }) {
  const [tf, setTf] = useState<Timeframe>('M')
  const [mode, setMode] = useState<'sectors' | 'industries'>('sectors')

  const secVal = (r: any, t: Timeframe) => t === 'W' ? r.rs5 : t === 'M' ? r.rs20 : r.rs60
  const indVal = (g: any, t: Timeframe) => t === 'W' ? g.rel1w : t === 'M' ? g.rel1m
    : (g.perf_quarter != null && spyLong != null ? +(g.perf_quarter - spyLong).toFixed(1) : null)

  const sectorRows = useMemo(() => {
    const longer: Timeframe = tf === 'W' ? 'M' : tf === 'M' ? 'Q' : 'M'
    return sectors.map(r => ({ name: r.sector, value: secVal(r, tf), prevValue: secVal(r, longer), state: r.state, book: r.book_pct ?? 0 }))
  }, [sectors, tf])

  const industryRows = useMemo(() => {
    const longer: Timeframe = tf === 'W' ? 'M' : tf === 'M' ? 'Q' : 'M'
    const rows = industries.map(g => ({ name: g.industry, value: indVal(g, tf), prevValue: indVal(g, longer), state: g.state, book: g.held?.length ? 3 : 0 }))
    const ordered = rows.filter(r => r.value != null).sort((a, b) => (b.value as number) - (a.value as number))
    // scope = the 16 rendered rows; chipScope re-ranks within this scope only
    return [...ordered.slice(0, 8), ...ordered.slice(-8)]
  }, [industries, tf, spyLong])

  const dots: Dot[] = useMemo(() => {
    if (mode === 'sectors') {
      return sectors.filter(r => secVal(r, tf) != null && r.slope != null)
        .map(r => ({ key: r.etf, label: r.sector, x: secVal(r, tf), y: r.slope, book: r.book_pct ?? 0, state: r.state }))
    }
    const withVal = industries.filter(g => indVal(g, tf) != null && g.rel1w != null)
      .sort((a, b) => (indVal(b, tf) as number) - (indVal(a, tf) as number))
    const held = withVal.filter(g => g.held?.length || g.watched?.length)
    const picks = new Set([...withVal.slice(0, 7), ...withVal.slice(-7), ...held])
    return [...picks].map(g => ({
      key: g.industry, label: g.industry.length > 24 ? g.industry.slice(0, 22) + '…' : g.industry,
      x: indVal(g, tf) as number, y: tf === 'W' ? (g.change_1d ?? 0) : g.rel1w, book: g.held?.length ? 4 : 0, state: g.state,
    }))
  }, [mode, sectors, industries, tf, spyLong])

  // axes fit the data (min floor keeps tiny spreads readable) — clamped edge dots
  // were piling labels off-canvas with fixed maxima
  const fit = (vals: number[], floor: number) => Math.max(floor, ...vals.map(Math.abs)) * 1.2
  const axis = {
    x: mode === 'sectors' ? `RS ${tf === 'W' ? '5d' : tf === 'M' ? '20d' : '60d'}` : `rel ${tf === 'W' ? '1w' : tf === 'M' ? '1m' : '1q'} vs SPY`,
    y: mode === 'sectors' ? 'RS20 slope' : tf === 'W' ? '1d change' : 'rel 1w',
    xMax: fit(dots.map(d => d.x), 4),
    yMax: fit(dots.map(d => d.y), 2),
  }

  const tfBtn = (t: Timeframe, label: string) => (
    <button key={t} onClick={() => setTf(t)} style={{
      fontSize: DASH.data, fontWeight: 800, padding: '2px 10px', cursor: 'pointer', borderRadius: 2,
      color: tf === t ? BB.text1 : BB.text3, background: tf === t ? BB.border : 'transparent', border: `1px solid ${BB.border}`,
    }}>{label}</button>
  )

  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '10px 12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: DASH.panel, fontWeight: 800, color: BB.text1 }}>Rotation</span>
        <div style={{ display: 'flex', gap: 4 }}>
          {tfBtn('W', 'W · 5d')}{tfBtn('M', 'M · 1m')}{tfBtn('Q', 'Q · 3m')}
          <span style={{ width: 10 }} />
          {(['sectors', 'industries'] as const).map(m => (
            <button key={m} onClick={() => setMode(m)} style={{
              fontSize: DASH.data, fontWeight: 700, padding: '2px 10px', cursor: 'pointer', borderRadius: 2, textTransform: 'capitalize',
              color: mode === m ? BB.text1 : BB.text3, background: mode === m ? BB.border : 'transparent', border: `1px solid ${BB.border}`,
            }}>{m}</button>
          ))}
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(360px, 6fr) minmax(280px, 3fr) minmax(280px, 3fr)', gap: 14, alignItems: 'start' }}>
        <Scatter dots={dots} xLabel={axis.x} yLabel={axis.y} xMax={axis.xMax} yMax={axis.yMax} />
        <Board title={`Sectors · ${tf}`} rows={sectorRows} tf={tf} />
        <Board title={`Industries · ${tf} (top/bottom 8)`} rows={industryRows} tf={tf} />
      </div>
      <div style={{ fontSize: DASH.chip, color: BB.text3, marginTop: 6 }}>
        ▲▼ = rank change vs the {tf === 'W' ? 'M' : tf === 'M' ? 'Q' : 'M'} view, within this list ·
        <span style={{ color: T.link }}> ●</span> new to the list at this timeframe · bar = your effective book weight · values are rel-SPY
      </div>
    </div>
  )
}
