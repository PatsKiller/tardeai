import { useMemo, useState } from 'react'
import { BB, T, TYPE, RAIL, numStyle } from '../lib/watchTokens'
import { Chip } from './TerminalChip'
import type { DrillContext } from './DetailDrawer'

/**
 * Sector entry routes — the two ways to express a sector view, side by side.
 *
 * GOVERNANCE: config/strategies/sector_rotation.yaml is PARKED — "portfolio overlay,
 * not a proposal generator; insufficient evidence" (2026-06-11). So this panel is
 * evidence for an operator review, NOT a proposal generator. It creates no proposal,
 * no order and no position size, and it invents nothing: the ETF lane shows the
 * sector's own ETF from that strategy's universe, and the stock lane shows only
 * candidates that already survived the CIO-verdict and coverage filters upstream.
 * Missing evidence stays visibly missing rather than being filled in.
 */

type Props = { sectors: any[]; onDrill: (ctx: DrillContext) => void }

const momTone = (m?: string) => m === 'leading' ? BB.green : m === 'lagging' ? BB.red : BB.text3
const momRail = (m?: string) => m === 'leading' ? RAIL.favorable : m === 'lagging' ? RAIL.breach : RAIL.neutral

function pct(v: any, digits = 1): string {
  const n = Number(v)
  return v == null || !Number.isFinite(n) ? '—' : `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`
}

export default function SectorEntryIdeas({ sectors, onDrill }: Props) {
  const [open, setOpen] = useState<string | null>(null)
  const [scope, setScope] = useState<'leading' | 'all'>('leading')

  const rows = useMemo(() => {
    const withRs = sectors.filter(s => s.etf)
    const ordered = [...withRs].sort((a, b) => (Number(b.rel_strength) || -999) - (Number(a.rel_strength) || -999))
    return scope === 'leading' ? ordered.filter(s => s.momentum === 'leading') : ordered
  }, [sectors, scope])

  if (!sectors.length) return null

  return (
    <div style={{ background: BB.bg, border: `1px solid ${BB.border}`, borderRadius: 2, padding: '12px 14px', marginBottom: 14 }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <div style={{ fontSize: TYPE.lg, fontWeight: 800, color: BB.text0 }}>SECTOR ENTRY ROUTES</div>
        <div style={{ fontSize: TYPE.xs, color: BB.text3, flex: 1, minWidth: 260 }}>
          Two ways to express a sector view — the sector ETF, or a qualified stock inside it.
          Advisory evidence for review; nothing here creates a proposal, order or position size.
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {(['leading', 'all'] as const).map(k => (
            <button key={k} onClick={() => setScope(k)}
              style={{
                fontSize: TYPE.xs, fontWeight: 800, padding: '4px 9px', borderRadius: 2, cursor: 'pointer',
                border: `1px solid ${scope === k ? T.link : BB.border}`,
                background: scope === k ? BB.bgShift : 'transparent',
                color: scope === k ? T.link : BB.text3,
              }}>
              {k === 'leading' ? 'LEADING ONLY' : 'ALL SECTORS'}
            </button>
          ))}
        </div>
      </div>

      <div
        title="sector_rotation.yaml is PARKED — a portfolio overlay, not a proposal generator (insufficient evidence, 2026-06-11). Treat these as review evidence, not signals."
        style={{ marginTop: 8, padding: '5px 8px', border: `1px solid ${BB.border}`, borderLeft: `3px solid ${RAIL.neutral}`, borderRadius: 2, fontSize: TYPE.xs, color: BB.text3 }}
      >
        <b style={{ color: BB.text2 }}>OVERLAY, NOT A SIGNAL:</b> the sector-rotation strategy is PARKED
        (portfolio overlay, not a proposal generator). Entries still go through the normal Proposals path.
      </div>

      {rows.length === 0 && (
        <div style={{ marginTop: 10, fontSize: TYPE.sm, color: BB.text3 }}>
          No sector is currently leading. Switch to ALL SECTORS to review the full board.
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))', gap: 8, marginTop: 10 }}>
        {rows.map(s => {
          const isOpen = open === s.sector
          const cands: any[] = (s.candidates || []).filter((c: any) => !c.cio_avoid)
          const avoided = (s.candidates || []).length - cands.length
          return (
            <div key={s.sector} style={{ border: `1px solid ${BB.border}`, borderLeft: `3px solid ${momRail(s.momentum)}`, borderRadius: 2, padding: '9px 10px', background: BB.bgShift }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 7, flexWrap: 'wrap' }}>
                <span style={{ fontSize: TYPE.md, fontWeight: 800, color: BB.text0 }}>{s.sector}</span>
                <span style={{ ...numStyle, fontSize: TYPE.xs, fontWeight: 800, color: momTone(s.momentum) }}>
                  {String(s.momentum || '—').toUpperCase()} {pct(s.rel_strength, 2)} vs SPY
                </span>
                {s.book_flag === 'overweight_lagging' && (
                  <Chip kind="state" tone="red" title="you are overweight this sector while its relative strength is deteriorating">OVERWEIGHT · LAGGING</Chip>
                )}
              </div>

              {/* ETF route — the sector's own ETF, from the sector_rotation universe */}
              <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', border: `1px solid ${BB.border}`, borderRadius: 2 }}>
                <span style={{ fontSize: TYPE.xs, fontWeight: 800, color: BB.text3, width: 34 }}>ETF</span>
                <span
                  onClick={() => onDrill({ title: s.etf, subtitle: `${s.sector} sector ETF`, endpoint: `/api/v2/watch/provenance/${s.etf}`, rows: [s] })}
                  style={{ ...numStyle, fontSize: TYPE.sm, fontWeight: 800, color: T.link, cursor: 'pointer' }}
                >{s.etf}</span>
                <span style={{ ...numStyle, fontSize: TYPE.xs, color: BB.text3 }}>day {pct(s.etf_change_pct, 2)}</span>
                <span
                  title="your current exposure to this sector via fund look-through on holdings"
                  style={{ ...numStyle, fontSize: TYPE.xs, color: BB.text3, marginLeft: 'auto' }}
                >you hold {pct(s.book_weight_pct)}</span>
              </div>

              {/* Stock route — only names that already cleared CIO-verdict + coverage */}
              <div style={{ marginTop: 6 }}>
                <button
                  onClick={() => setOpen(isOpen ? null : s.sector)}
                  disabled={!cands.length}
                  title={cands.length ? 'score-ranked candidates that survived the CIO-verdict and coverage filters' : 'no candidate in this sector cleared the CIO-verdict and coverage filters'}
                  style={{
                    width: '100%', textAlign: 'left', fontSize: TYPE.xs, fontWeight: 800, padding: '5px 8px', borderRadius: 2,
                    cursor: cands.length ? 'pointer' : 'default',
                    border: `1px solid ${BB.border}`, background: 'transparent',
                    color: cands.length ? BB.text2 : BB.text3,
                  }}
                >
                  STOCKS · {cands.length ? `${cands.length} qualified${avoided ? ` · ${avoided} CIO-avoid hidden` : ''}` : 'none cleared the filters'} {cands.length ? (isOpen ? '▾' : '▸') : ''}
                </button>
                {isOpen && cands.map((c: any) => (
                  <div key={`${c.symbol}-${c.origin_system}`}
                    onClick={() => onDrill({ title: c.symbol, subtitle: `${s.sector} candidate`, endpoint: `/api/v2/watch/provenance/${c.symbol}`, rows: [c] })}
                    title={`${c.symbol}: ${c.setup_advisory || 'no advisory'} · origin ${c.origin_system || 'unknown'}${c.cio_view ? ` · CIO ${c.cio_view}` : ''}`}
                    style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '4px 8px', marginTop: 4, borderRadius: 2, background: BB.bg, cursor: 'pointer' }}>
                    <span style={{ ...numStyle, fontSize: TYPE.sm, fontWeight: 800, color: BB.text0, width: 58 }}>{c.symbol}</span>
                    <span style={{ ...numStyle, fontSize: TYPE.xs, color: BB.text3 }}>RSI {c.rsi == null ? '—' : Number(c.rsi).toFixed(0)}</span>
                    <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>{String(c.trend || '—')}</span>
                    {c.cio_view && <Chip kind="state" tone="slate" title="CIO verdict recorded for this name">{String(c.cio_view).replace(/_/g, ' ')}</Chip>}
                    <span style={{ fontSize: TYPE.xs, color: c.thin_coverage ? BB.amber : BB.text3, marginLeft: 'auto' }}>
                      {c.thin_coverage ? 'thin coverage' : `${c.analyst_opinions ?? 0} analysts`}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
