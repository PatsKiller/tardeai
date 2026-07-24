import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { BB, T, TYPE, RAIL, numStyle } from '../lib/watchTokens'
import { Chip } from './TerminalChip'
import type { DrillContext } from './DetailDrawer'

/**
 * Sub-sector leaders by Street analyst evidence.
 *
 * The sector board works at ETF level and the industry board at group level; neither
 * could answer "which individual names inside this sub-sector do analysts actually
 * like". This closes that gap.
 *
 * Upside is arithmetic on the stored mean target versus the stored price — not a
 * forecast and not a recommendation. Names below the analyst-count floor are excluded
 * upstream rather than shown as zero, and each row carries its analyst count so thin
 * coverage stays visible. Advisory only: no proposal, order or size is created here.
 */

type Leader = {
  symbol: string; analysts: number; consensus: string | null
  target_mean: number | null; price: number | null; upside_pct: number | null
  as_of: string | null; held: boolean
}
type Bucket = {
  industry: string; sector: string | null; state: string | null
  rel1w: number | null; rel1m: number | null; covered_names: number; leaders: Leader[]
}

const stateTone = (s?: string | null) =>
  s === 'LEADING' ? BB.green : s === 'IMPROVING' ? T.link : s === 'WEAKENING' ? BB.amber : s === 'LAGGING' ? BB.red : BB.text3
const stateRail = (s?: string | null) =>
  s === 'LEADING' ? RAIL.favorable : s === 'LAGGING' ? RAIL.breach : RAIL.neutral

function consensusTone(c: string | null): string {
  const v = String(c || '').toLowerCase()
  if (v === 'strong_buy' || v === 'buy') return BB.green
  if (v === 'sell' || v === 'strong_sell' || v === 'underperform') return BB.red
  if (v === 'hold') return BB.text2
  return BB.text3
}

function pct(v: number | null | undefined): string {
  return v == null || !Number.isFinite(Number(v)) ? '—' : `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(1)}%`
}

export default function IndustryAnalystLeaders({ onDrill, sectorFilter }: { onDrill: (c: DrillContext) => void; sectorFilter?: string | null }) {
  const [minAnalysts, setMinAnalysts] = useState(3)
  const [open, setOpen] = useState<string | null>(null)
  const { data } = useApi<any>(`/api/v2/sectors/industry-leaders?state=LEADING,IMPROVING&min_analysts=${minAnalysts}&limit_per=6`, 300_000)

  const buckets: Bucket[] = useMemo(() => {
    const all: Bucket[] = data?.industries || []
    return sectorFilter ? all.filter(b => b.sector === sectorFilter) : all
  }, [data, sectorFilter])

  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '12px 14px', marginBottom: 14 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <div style={{ fontSize: TYPE.lg, fontWeight: 800, color: BB.text0 }}>SUB-SECTOR LEADERS · BY ANALYST</div>
        <div style={{ fontSize: TYPE.xs, color: BB.text3, flex: 1, minWidth: 250 }}>
          Individual names inside each leading or improving industry group, ranked by mean
          analyst target versus price. Advisory evidence — not a forecast, proposal or size.
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>min analysts</span>
          {[3, 5, 10].map(n => (
            <button key={n} onClick={() => setMinAnalysts(n)}
              style={{
                fontSize: TYPE.xs, fontWeight: 800, padding: '4px 8px', borderRadius: 2, cursor: 'pointer',
                border: `1px solid ${minAnalysts === n ? T.link : BB.border}`,
                background: minAnalysts === n ? BB.bgShift : 'transparent',
                color: minAnalysts === n ? T.link : BB.text3,
              }}>{n}+</button>
          ))}
        </div>
      </div>

      {!data && <div style={{ marginTop: 10, fontSize: TYPE.sm, color: BB.text3 }}>Loading sub-sector analyst coverage…</div>}
      {data && buckets.length === 0 && (
        <div style={{ marginTop: 10, fontSize: TYPE.sm, color: BB.text3 }}>
          No leading or improving sub-sector has a name with {minAnalysts}+ covering analysts. Lower the floor to widen coverage.
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(340px,1fr))', gap: 8, marginTop: 10 }}>
        {buckets.slice(0, open ? undefined : 12).map(b => {
          const isOpen = open === b.industry
          const shown = isOpen ? b.leaders : b.leaders.slice(0, 3)
          return (
            <div key={b.industry} style={{ border: `1px solid ${BB.border}`, borderLeft: `3px solid ${stateRail(b.state)}`, borderRadius: 2, padding: '9px 10px', background: BB.bgShift }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 7, flexWrap: 'wrap' }}>
                <span style={{ fontSize: TYPE.sm, fontWeight: 800, color: BB.text0 }}>{b.industry}</span>
                <Chip kind="state" tone={b.state === 'LEADING' ? 'green' : 'slate'} title="closed-session industry momentum quadrant">{b.state || '—'}</Chip>
                <span style={{ ...numStyle, fontSize: TYPE.xs, color: stateTone(b.state) }} title="industry relative strength vs SPY over ~1 month">
                  {pct(b.rel1m)} 1M
                </span>
                <span style={{ fontSize: TYPE.xs, color: BB.text3, marginLeft: 'auto' }}>{b.sector}</span>
              </div>

              {shown.map(L => (
                <div key={L.symbol}
                  onClick={() => onDrill({ title: L.symbol, subtitle: `${b.industry} · analyst leader`, endpoint: `/api/v2/watch/provenance/${L.symbol}`, rows: [L as any] })}
                  title={`${L.symbol}: ${L.analysts} covering analysts · consensus ${L.consensus || 'none'} · mean target ${L.target_mean == null ? 'n/a' : `$${L.target_mean.toFixed(2)}`} vs price ${L.price == null ? 'n/a' : `$${L.price.toFixed(2)}`}${L.as_of ? ` · as of ${L.as_of}` : ''}. Arithmetic upside, not a forecast.`}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 8px', marginTop: 5, borderRadius: 2, background: BB.bg, cursor: 'pointer' }}>
                  <span style={{ ...numStyle, fontSize: TYPE.sm, fontWeight: 800, color: BB.text0, width: 56 }}>{L.symbol}</span>
                  <span style={{ ...numStyle, fontSize: TYPE.sm, fontWeight: 800, color: (L.upside_pct ?? 0) >= 0 ? BB.green : BB.red, width: 62 }}>{pct(L.upside_pct)}</span>
                  <span style={{ fontSize: TYPE.xs, fontWeight: 800, color: consensusTone(L.consensus) }}>{String(L.consensus || 'none').replace(/_/g, ' ')}</span>
                  <span style={{ ...numStyle, fontSize: TYPE.xs, color: BB.text3 }}>{L.analysts} an.</span>
                  {L.held && <Chip kind="state" tone="amber" title="you already hold this name">HELD</Chip>}
                </div>
              ))}

              {b.leaders.length > 3 && (
                <button onClick={() => setOpen(isOpen ? null : b.industry)}
                  style={{ marginTop: 5, fontSize: TYPE.xs, fontWeight: 800, background: 'transparent', border: 'none', color: T.link, cursor: 'pointer', padding: 0 }}>
                  {isOpen ? 'show fewer' : `+${b.leaders.length - 3} more · ${b.covered_names} covered in group`}
                </button>
              )}
            </div>
          )
        })}
      </div>

      {data && buckets.length > 12 && !open && (
        <div style={{ marginTop: 8, fontSize: TYPE.xs, color: BB.text3 }}>
          Showing the 12 strongest of {buckets.length} qualifying sub-sectors, ranked by 1-month relative strength.
        </div>
      )}
    </div>
  )
}
