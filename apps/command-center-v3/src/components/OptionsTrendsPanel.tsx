import { useMemo, useState } from 'react'
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Cell,
} from 'recharts'
import { useApi } from '../hooks/useApi'
import { Tip, TipKpi, TipSection } from './OptionsTip'
import { TRENDS } from '../lib/optionsTooltips'

const panel = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 } as const
const SEL: React.CSSProperties = { fontSize: 11, padding: '6px 9px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text0)' }
const BLUE = '#60a5fa'
const PURPLE = '#a855f7'
const GREEN = '#22c55e'
const AMBER = '#f59e0b'

type TermPoint = { exp: string; dte: number; atm_iv_pct: number | null; put_call_skew_pct: number | null }
type SurfaceCell = { strike: number; dte: number; iv_pct: number | null }
type HistPoint = { captured_at: string; front_iv_pct?: number; term_slope_pct?: number; avg_put_skew_pct?: number }

function ivColor(iv: number | null | undefined): string {
  if (iv == null) return 'var(--bg2)'
  if (iv >= 80) return 'rgba(239,68,68,.55)'
  if (iv >= 50) return 'rgba(245,158,11,.45)'
  if (iv >= 30) return 'rgba(96,165,250,.4)'
  return 'rgba(34,197,94,.35)'
}

function slopeLabel(slope: number | null | undefined): string {
  if (slope == null) return '—'
  if (slope > 3) return 'backwardation'
  if (slope < -3) return 'contango'
  return 'flat'
}

export default function OptionsTrendsPanel({
  defaultSymbol,
  proposalSymbols,
}: {
  defaultSymbol?: string
  proposalSymbols: string[]
}) {
  const [symbol, setSymbol] = useState(defaultSymbol || proposalSymbols[0] || 'RTX')

  const { data: trends, loading: trendsLoading, refetch: refetchTrends } = useApi<any>('/api/v2/options/desk/trends', 300_000)
  const volQ = symbol ? `?symbol=${encodeURIComponent(symbol.toUpperCase())}` : ''
  const { data: vol, loading: volLoading, error: volError, refetch: refetchVol } = useApi<any>(
    `/api/v2/options/desk/vol-analytics${volQ}`,
    180_000,
    { enabled: !!symbol },
  )
  const { data: histWrap } = useApi<any>(
    `/api/v2/options/desk/vol-history?symbol=${encodeURIComponent(symbol.toUpperCase())}&limit=48`,
    300_000,
    { enabled: !!symbol },
  )

  const isTicker = (s: string) => /^[A-Z]{1,5}(\.[A-Z])?$/.test(s)

  const deskSymbols: string[] = useMemo(() => {
    const fromApi = (trends?.symbols || []).map((s: { symbol: string }) => s.symbol)
    const merged = [...new Set([...proposalSymbols, ...fromApi])].filter(s => s && isTicker(s)).sort()
    return merged.length ? merged : ['RTX', 'NOC', 'SCHD']
  }, [trends, proposalSymbols])

  const symMeta = (trends?.symbols || []).find((s: { symbol: string }) => s.symbol === symbol.toUpperCase())
  const term: TermPoint[] = vol?.term_structure || vol?.data?.term_structure || []
  const surface = vol?.surface || vol?.data?.surface
  const history: HistPoint[] = histWrap?.history || histWrap?.data?.history || []
  const underlying = vol?.underlying ?? surface?.underlying

  const termChart = term.filter(t => t.atm_iv_pct != null).map(t => ({
    label: `${t.dte}d`,
    dte: t.dte,
    iv: t.atm_iv_pct,
    skew: t.put_call_skew_pct,
  }))

  const skewChart = term.filter(t => t.put_call_skew_pct != null).map(t => ({
    label: `${t.dte}d`,
    skew: t.put_call_skew_pct,
  }))

  const histChart = history.filter(h => h.front_iv_pct != null).map(h => ({
    t: new Date(h.captured_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
    front: h.front_iv_pct,
    skew: h.avg_put_skew_pct,
  }))

  const heatmap = useMemo(() => {
    if (!surface?.ok || !surface.cells?.length) return null
    const strikes: number[] = surface.strikes || []
    const dtes: number[] = (surface.expiries || []).map((e: { dte: number }) => e.dte)
    const cellMap = new Map<string, number | null>()
    for (const c of surface.cells as SurfaceCell[]) {
      cellMap.set(`${c.dte}:${c.strike}`, c.iv_pct)
    }
    return { strikes, dtes, cellMap, underlying: surface.underlying }
  }, [surface])

  const refresh = () => { refetchTrends(); refetchVol() }

  return (
    <div>
      <div style={{ ...panel, marginBottom: 14 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 10 }}>
          <TipSection tip={TRENDS.symbol}>VOL ANALYTICS ⓘ</TipSection>
          <input
            placeholder="Symbol"
            title={TRENDS.symbol}
            value={symbol}
            onChange={e => setSymbol(e.target.value.toUpperCase())}
            style={{ ...SEL, width: 72, cursor: 'help' }}
          />
          <button type="button" title={TRENDS.refresh} onClick={refresh} style={{ ...SEL, cursor: 'help' }}>Refresh chain</button>
          {(trendsLoading || volLoading) && <span style={{ fontSize: 10, color: 'var(--text3)' }}>Loading…</span>}
          {volError && <span style={{ fontSize: 10, color: '#ef4444' }}>{volError}</span>}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {deskSymbols.slice(0, 24).map(s => (
            <button
              key={s}
              type="button"
              title={TRENDS.symbolChip}
              onClick={() => setSymbol(s)}
              style={{
                padding: '4px 10px', fontSize: 10, borderRadius: 5, cursor: 'help',
                border: `1px solid ${symbol.toUpperCase() === s ? BLUE : 'var(--border)'}`,
                background: symbol.toUpperCase() === s ? `${BLUE}22` : 'var(--bg2)',
                color: symbol.toUpperCase() === s ? BLUE : 'var(--text3)',
                fontWeight: symbol.toUpperCase() === s ? 700 : 500,
              }}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {symMeta?.research?.length > 0 && (
        <div title={TRENDS.research} style={{ ...panel, marginBottom: 14, borderLeft: '4px solid #a855f7', cursor: 'help' }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: PURPLE, marginBottom: 8 }}>Desk research · {symbol} ⓘ</div>
          {symMeta.research.slice(0, 2).map((r: { strategy?: string; recommended_action?: string; edge_score?: number; pop_pct?: number }, i: number) => (
            <div key={i} style={{ fontSize: 10.5, color: 'var(--text2)', marginBottom: 4 }}>
              <b>{(r.strategy || '').replace(/_/g, ' ')}</b> — {r.recommended_action} · edge {r.edge_score} · POP {r.pop_pct}%
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10, marginBottom: 14 }}>
        <TipKpi tip={TRENDS.frontIv} label="Front IV" value={vol?.front_iv_pct != null ? `${vol.front_iv_pct}%` : '—'} color={AMBER} />
        <TipKpi tip={TRENDS.backIv} label="Back IV" value={vol?.back_iv_pct != null ? `${vol.back_iv_pct}%` : '—'} color={BLUE} />
        <TipKpi tip={TRENDS.termSlope} label="Term slope" value={vol?.term_slope_pct != null ? `${vol.term_slope_pct}% (${slopeLabel(vol.term_slope_pct)})` : '—'} color={PURPLE} />
        <TipKpi tip={TRENDS.skew} label="Avg put skew" value={vol?.avg_put_skew_pct != null ? `${vol.avg_put_skew_pct}%` : '—'} color={GREEN} />
        <TipKpi tip={TRENDS.spot} label="Spot" value={underlying != null ? `$${underlying}` : '—'} color="var(--text2)" />
        <TipKpi tip={TRENDS.ivRank} label="IV rank (desk)" value={symMeta?.iv_rank != null ? `${symMeta.iv_rank}%` : '—'} color="var(--text2)" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12, marginBottom: 14 }}>
        <div title={TRENDS.termChart} style={{ ...panel, cursor: 'help' }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text0)', marginBottom: 8 }}>IV term structure ⓘ</div>
          {termChart.length === 0 ? (
            <div style={{ fontSize: 10, color: 'var(--text3)' }}>No ATM IV — try another symbol or refresh.</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={termChart} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
                <XAxis dataKey="label" tick={{ fontSize: 9, fill: 'var(--text3)' }} />
                <YAxis tick={{ fontSize: 9, fill: 'var(--text3)' }} width={36} unit="%" />
                <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} />
                <Line type="monotone" dataKey="iv" stroke={AMBER} strokeWidth={2} dot={{ r: 3 }} name="ATM IV %" />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>

        <div title={TRENDS.skewChart} style={{ ...panel, cursor: 'help' }}>
          <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text0)', marginBottom: 8 }}>Put/call skew by DTE ⓘ</div>
          {skewChart.length === 0 ? (
            <div style={{ fontSize: 10, color: 'var(--text3)' }}>Skew unavailable for this chain.</div>
          ) : (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={skewChart} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
                <XAxis dataKey="label" tick={{ fontSize: 9, fill: 'var(--text3)' }} />
                <YAxis tick={{ fontSize: 9, fill: 'var(--text3)' }} width={40} unit="%" />
                <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} />
                <Bar dataKey="skew" name="Put−Call IV %" radius={[4, 4, 0, 0]}>
                  {skewChart.map((_, i) => <Cell key={i} fill={i % 2 ? PURPLE : BLUE} />)}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div title={TRENDS.surface} style={{ ...panel, marginBottom: 14, cursor: 'help' }}>
        <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text0)', marginBottom: 8 }}>IV surface (strike × DTE) ⓘ</div>
        {!heatmap ? (
          <div style={{ fontSize: 10, color: 'var(--text3)' }}>Surface grid loads with live Schwab chain — select a symbol above.</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', fontSize: 9, minWidth: '100%' }}>
              <thead>
                <tr>
                  <th style={{ padding: 4, color: 'var(--text3)', textAlign: 'left' }}>Strike ↓ / DTE →</th>
                  {heatmap.dtes.map(d => (
                    <th key={d} style={{ padding: 4, color: 'var(--text3)', textAlign: 'center' }}>{d}d</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {heatmap.strikes.map(strike => (
                  <tr key={strike}>
                    <td style={{ padding: 4, color: 'var(--text2)', fontWeight: 700 }}>${strike}</td>
                    {heatmap.dtes.map(dte => {
                      const iv = heatmap.cellMap.get(`${dte}:${strike}`)
                      return (
                        <td
                          key={`${strike}-${dte}`}
                          title={iv != null ? `IV ${iv}%` : 'no quote'}
                          style={{
                            padding: 6, textAlign: 'center', minWidth: 44,
                            background: ivColor(iv),
                            color: iv != null ? 'var(--text0)' : 'var(--text3)',
                            border: '1px solid var(--border)',
                          }}
                        >
                          {iv != null ? `${iv}%` : '—'}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>
              Spot ${heatmap.underlying} · green = lower IV · red = elevated IV · ±12% strike window
            </div>
          </div>
        )}
      </div>

      <div title={TRENDS.history} style={{ ...panel, cursor: 'help' }}>
        <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--text0)', marginBottom: 8 }}>IV history (snapshots) ⓘ</div>
        {histChart.length < 2 ? (
          <div style={{ fontSize: 10, color: 'var(--text3)' }}>
            History builds as you view symbols on this tab — each refresh saves a snapshot.
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={histChart} margin={{ top: 8, right: 8, left: 0, bottom: 4 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" />
              <XAxis dataKey="t" tick={{ fontSize: 8, fill: 'var(--text3)' }} interval="preserveStartEnd" />
              <YAxis tick={{ fontSize: 9, fill: 'var(--text3)' }} width={36} unit="%" />
              <Tooltip contentStyle={{ background: 'var(--bg1)', border: '1px solid var(--border)', fontSize: 10 }} />
              <Line type="monotone" dataKey="front" stroke={AMBER} strokeWidth={2} dot={false} name="Front IV %" />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}