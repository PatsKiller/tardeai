import { useMemo, useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import WatchlistHub from './WatchlistHub'
import { useTerminalUi } from '../lib/terminalUi'
import { hubStrip, BB, T, TYPE, RAIL, numStyle } from '../lib/watchTokens'
import { Chip } from '../components/TerminalChip'

interface Props { onDrill: (ctx: DrillContext) => void; embedded?: boolean }

// v4 (WS-D): converted-α breakdown in the header, per-source metric chips that FILTER
// the emissions band (D3), and the low-efficacy fold (D2) — visibility is the throttle,
// nothing is blocked or deleted; the label lifts when the rolling α recovers.

const alphaTxt = (v: any, n?: any) =>
  v != null ? `${v > 0 ? '+' : ''}${v}%${n != null ? ` (n=${n})` : ''}` : 'n/a'

export default function ScreenerFindsHub({ onDrill, embedded }: Props) {
  const [terminalUi] = useTerminalUi()
  const { data } = useApi<any>('/api/v2/screener-finds/candidates', 60_000)
  const count = data?.count ?? 0
  const tr = data?.track_record ?? {}
  const perSource: any[] = tr.per_source ?? []
  const [srcFilter, setSrcFilter] = useState<string | null>(null)
  const [showLowEff, setShowLowEff] = useState(false)

  const wide: any[] = data?.wide_finds ?? []
  const filtered = useMemo(() => srcFilter ? wide.filter(f => f.source_type === srcFilter) : wide, [wide, srcFilter])
  const main = filtered.filter(f => !f.low_efficacy_source)
  const lowEff = filtered.filter(f => f.low_efficacy_source)

  const Row = (f: any, i: number) => (
    <div key={i} style={{ display: 'flex', gap: 10, fontSize: TYPE.sm, padding: '3px 6px', borderBottom: `1px solid ${BB.borderHair}`,
                          borderLeft: `3px solid ${f.alpha_21d == null ? RAIL.neutral : f.alpha_21d > 0 ? RAIL.favorable : RAIL.breach}`, alignItems: 'baseline' }}>
      <span style={{ ...numStyle, fontWeight: 800, minWidth: 52, color: BB.text0 }}>{f.symbol}</span>
      <span style={{ color: BB.text3, minWidth: 92, cursor: 'pointer', textDecoration: 'underline dotted' }}
            title="filter this band to this source"
            onClick={() => setSrcFilter(s => s === f.source_type ? null : f.source_type)}>{f.source_type}</span>
      <span style={{ color: BB.text3, minWidth: 78 }}>{f.emitted_on}</span>
      <span style={{ ...numStyle, minWidth: 96, color: f.alpha_21d == null ? BB.text3 : f.alpha_21d > 0 ? BB.green : BB.red }}>
        {f.alpha_21d != null ? `21d α ${f.alpha_21d > 0 ? '+' : ''}${f.alpha_21d}%` : (f.verdict || 'pending')}
      </span>
      {f.proposed && <span style={{ color: T.link }}>→ proposal</span>}
    </div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: terminalUi ? 6 : 12 }}>
      <div className="cc-panel" style={hubStrip(terminalUi)}>
        <span style={{ fontWeight: 800, color: BB.amber, letterSpacing: '.06em' }}>SCREENER FINDS</span>
        {' · '}{count} CIO-qualified · auto-research lane
        {tr.n != null && (
          <>
            {' · '}last 90d: {tr.n} emissions · all-emissions α {alphaTxt(tr.median_alpha_21d, tr.scored)}
            {' · '}<b style={{ color: tr.converted_alpha_21d != null && tr.converted_alpha_21d < 0 ? BB.red : BB.green }}>
              converted α {alphaTxt(tr.converted_alpha_21d, tr.converted_scored)}</b>
            {' · '}{tr.converted} converted
          </>
        )}
      </div>

      {/* WS-D per-source scoreboard chips — click = filter the emissions band (D3) */}
      {perSource.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          {perSource.map((s: any) => (
            <span key={s.source_type} onClick={() => setSrcFilter(f => f === s.source_type ? null : s.source_type)}
                  title={`${s.source_type}: ${s.emitted} emitted · α ${alphaTxt(s.alpha_21d_median, s.n)} · converted α ${alphaTxt(s.converted_alpha_21d)} · ${s.converted} converted${s.low_efficacy ? ' · LOW-EFFICACY (gated fold below)' : ''} — click to filter`}
                  style={{ cursor: 'pointer', outline: srcFilter === s.source_type ? `1px solid ${BB.amber}` : 'none' }}>
              <Chip kind="metric">
                <span style={{ color: s.low_efficacy ? BB.red : BB.text2 }}>
                  {s.source_type} α {alphaTxt(s.alpha_21d_median, s.n)}
                </span>
              </Chip>
            </span>
          ))}
          {tr.gate?.alpha_floor_pct != null && (
            <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>
              gate: n≥{tr.gate.min_n} & α&lt;{tr.gate.alpha_floor_pct}% → folded (auto-lifts on recovery)
            </span>
          )}
          {srcFilter && <Chip kind="state" tone="amber">FILTER: {srcFilter}</Chip>}
        </div>
      )}

      <WatchlistHub onDrill={onDrill} embedded={embedded ?? true} lane="screener_finds" />

      {/* Watch Desk v3 (D1): full screener+discovery emissions, evidence attached */}
      {filtered.length > 0 && (
        <div className="cc-panel" style={{ padding: 12 }}>
          <div style={{ fontSize: TYPE.sm, fontWeight: 800, letterSpacing: '.06em', color: BB.text3, marginBottom: 6 }}>
            ALL FINDS (90d) — screener + discovery emissions · CIO-qualified subset highlighted above
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 360, overflowY: 'auto' }}>
            {main.slice(0, 60).map(Row)}
          </div>
          {/* D2: the low-efficacy fold — collapsed band, never hidden-hidden */}
          {lowEff.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <button onClick={() => setShowLowEff(v => !v)}
                      style={{ fontSize: TYPE.xs, fontWeight: 800, letterSpacing: '.05em', color: BB.amber,
                               background: BB.amberDim, border: `1px solid ${BB.amber}55`, borderRadius: 2,
                               padding: '3px 10px', cursor: 'pointer' }}>
                {showLowEff ? '▾' : '▸'} LOW-EFFICACY SOURCES ({lowEff.length}) — rolling 21d α below the gate floor; visibility throttled, auto-lifts on recovery
              </button>
              {showLowEff && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 300, overflowY: 'auto', marginTop: 6, opacity: 0.85 }}>
                  {lowEff.slice(0, 60).map(Row)}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
