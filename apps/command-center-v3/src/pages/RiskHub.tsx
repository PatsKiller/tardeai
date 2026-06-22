import { useEffect, useState } from 'react'
import { useApi } from '../hooks/useApi'
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts'
import type { DrillContext } from '../components/DetailDrawer'
import ProAnalystPill, { useProAnalystMap } from '../components/ProAnalystPill'
import AskAgents from '../components/AskAgents'

interface Props { onDrill: (ctx: DrillContext) => void }

const TABS = ['Exposure', 'Correlation', 'Regime', 'Recovery'] as const
const HEAT_THRESHOLD = 5.0

export default function RiskHub({ onDrill }: Props) {
  const [tab, setTab] = useState<typeof TABS[number]>('Exposure')
  const { data: risk } = useApi<any>('/api/v2/risk', 60_000)
  const { data: corr } = useApi<any>('/api/v2/correlation', 120_000)
  const { data: indicators } = useApi<any>('/api/v2/risk-regime/indicators', 120_000)
  const { data: history } = useApi<any>('/api/v2/risk-regime/history', 120_000)
  const { data: latest } = useApi<any>('/api/v2/risk-regime/latest', 120_000)
  const { data: recovery } = useApi<any>('/api/v2/recovery', 120_000)
  const paMap = useProAnalystMap()

  const heat = risk?.portfolio_heat_pct ?? 0
  const overThreshold = heat > HEAT_THRESHOLD
  const allPositions = risk?.positions ?? []
  // Real vs paper split (operator 2026-06-21): paper positions (Alpaca, environment="paper") carry real live
  // stops but are NOT real-money risk — default to real-money view, toggle to include/isolate paper. The
  // headline heat/risk KPIs are always real-money (precomputed, exclude paper).
  const [env, setEnv] = useState<'real' | 'all' | 'paper'>('all')
  const paperCount = allPositions.filter((p: any) => p.environment === 'paper').length
  const positions = env === 'all' ? allPositions : allPositions.filter((p: any) => (p.environment || 'real') === env)
  const triggered = positions.filter((p: any) => p.triggered)

  // Deep-link params from the Reports Action Queue: ?symbol / ?symbols / ?drawer (stop|stops|unprotected|
  // recovery) / ?tab. The effect below opens the EXACT drawer/tab so a stop action lands on that position's
  // stop detail, an "unprotected" action on the no-stop list, a recovery action on the Recovery tab, etc.
  const [dlp] = useState(() => { try { return new URLSearchParams(window.location.search) } catch { return new URLSearchParams() } })
  const [focused, setFocused] = useState(false)
  const [hlStops, setHlStops] = useState(false)   // highlight the triggered-stops panel (deep-link from Reports)

  // Open ONE position's stop detail (singular, not the whole stacked list) with a "Where to act" link to the
  // existing operator-gated approval/proposal flow (advisory — no broker write here).
  const stopDrill = (p: any) => onDrill({
    title: `${p.symbol} — stop ${p.triggered ? 'TRIGGERED' : p.has_stop ? '' : 'MISSING'}`.trim(),
    subtitle: `stop ${p.stop_price ?? p.stop ?? '—'} · current ${p.current_price ?? '—'}${p.distance_to_stop_pct != null ? ` · ${p.distance_to_stop_pct}% past` : ''}${p.account ? ` · ${p.account}` : ''}`,
    endpoint: '/api/v2/risk', rows: [p],
    links: [{ label: `Arm protective stop / ignore 1wk — ${p.symbol}`, href: `/v3/trading?tab=Open%20Trades&symbol=${p.symbol}`, note: 'opens the Stage 2c protective-stop card for this position: ARM a live protective stop (operator 2FA) or acknowledge with a 1-week grace period' }],
  })

  const noStop = positions.filter((p: any) => !p.has_stop)
  // Canonical protection (reconciled 2026-06-21): VERIFIED = a live broker stop order OR an operator-confirmed
  // stop (broker_protected). PLANNED = a risk_management stop that is NOT verified live (advisory only). The
  // old "protected" count conflated the two — a planned stop is not protection until it's live at the broker.
  const verifiedCount = positions.filter((p: any) => p.broker_protected).length
  const plannedOnly = positions.filter((p: any) => !p.broker_protected && p.has_stop).length
  const protectedCount = verifiedCount       // only verified live stops count as protected
  const exposedCount = positions.length - protectedCount

  // Correlation matrix
  const corrMatrix = corr?.correlation_matrix ?? {}
  const corrSymbols = Object.keys(corrMatrix)

  // Indicators for heatmap
  const indList: any[] = Array.isArray(indicators) ? indicators : []
  const signalColor = (s: string) => s === 'risk_on' ? '#22c55e' : s === 'risk_off' ? '#ef4444' : '#f59e0b'

  // History for regime timeline
  const histList: any[] = Array.isArray(history) ? history : []

  // Recovery items
  const recoveryItems = recovery?.items ?? []

  useEffect(() => {
    if (focused) return
    const tab = dlp.get('tab'); const drawer = dlp.get('drawer')
    const symbol = (dlp.get('symbol') || '').toUpperCase()
    const symbols = (dlp.get('symbols') || '').toUpperCase().split(',').map(s => s.trim()).filter(Boolean)
    if (tab && (TABS as readonly string[]).includes(tab)) setTab(tab as typeof TABS[number])
    const ready = positions.length > 0 || recoveryItems.length > 0
    if (!ready) return
    // Recovery deep-link
    if (drawer === 'recovery' || tab === 'Recovery') {
      if (symbol) {
        const r = recoveryItems.find((x: any) => String(x.symbol || '').toUpperCase() === symbol)
        if (r) { setFocused(true); onDrill({ title: `${r.symbol} Recovery`, subtitle: r.analyst_verdict ?? 'recovery watch', endpoint: '/api/v2/recovery', rows: [r] }) }
        else setFocused(true)
      } else setFocused(true)
      return
    }
    // Unprotected (no-stop) list
    if (drawer === 'unprotected') {
      setFocused(true)
      onDrill({ title: `Unprotected positions (${noStop.length})`, subtitle: 'no protective stop', endpoint: '/api/v2/risk', rows: noStop })
      return
    }
    // Grouped triggered stops (?symbols=A,B,C or ?drawer=stops): DON'T stack them all into one drawer —
    // land on the Exposure tab, highlight the triggered-stops panel, and let the operator click ONE symbol
    // to open its singular stop detail (operator: "opens all not singular").
    if (symbols.length || drawer === 'stops') {
      setFocused(true); setTab('Exposure'); setHlStops(true)
      setTimeout(() => document.getElementById('triggered-stops')?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 80)
      return
    }
    // Single-symbol stop detail (singular)
    if (symbol) {
      const p = positions.find((x: any) => String(x.symbol || '').toUpperCase() === symbol)
      if (p) { setFocused(true); stopDrill(p) }
      else setFocused(true)
    }
  }, [dlp, focused, positions, noStop, triggered, recoveryItems, onDrill])

  return (
    <div>
      <AskAgents examples={["Am I over-concentrated? What's my biggest single-name risk?", "What's the R:R if I trim my largest position 5%?"]} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Risk Hub</div>
          <div style={{ fontSize: 11, color: overThreshold ? '#ef4444' : 'var(--text3)' }}>
            heat {heat}%{overThreshold ? ' — over threshold' : ''} · {positions.length} positions
          </div>
        </div>
        <div style={{ display: 'flex', gap: 4 }}>
          {TABS.map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: '4px 12px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer',
              background: tab === t ? 'rgba(96,165,250,.15)' : 'var(--bg2)',
              color: tab === t ? '#60a5fa' : 'var(--text3)', fontWeight: tab === t ? 700 : 400,
            }}>{t}</button>
          ))}
        </div>
      </div>

      {tab === 'Exposure' && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: 16, marginBottom: 16 }}>
            {/* Heat gauge */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16, textAlign: 'center' }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Portfolio Heat</div>
              <ResponsiveContainer width="100%" height={140}>
                <PieChart>
                  <Pie data={[{ value: heat }, { value: Math.max(0, 15 - heat) }]}
                    cx="50%" cy="85%" startAngle={180} endAngle={0}
                    innerRadius={55} outerRadius={75} dataKey="value" stroke="none">
                    <Cell fill={overThreshold ? '#ef4444' : heat > 3 ? '#f59e0b' : '#22c55e'} />
                    <Cell fill="var(--bg2)" />
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div style={{ fontSize: 28, fontWeight: 700, color: overThreshold ? '#ef4444' : '#f59e0b', marginTop: -30 }}>{heat}%</div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>threshold {HEAT_THRESHOLD}% (hardcoded — no threshold field on endpoint)</div>
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 2 }}>field: portfolio_heat_pct</div>
            </div>

            {/* Protection coverage */}
            <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Protection Coverage</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {paperCount > 0 && (
                    <div style={{ display: 'flex', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
                      {(['all', 'real', 'paper'] as const).map((e) => (
                        <button key={e} onClick={() => setEnv(e)} style={{
                          fontSize: 9, fontWeight: 700, padding: '3px 8px', border: 'none', cursor: 'pointer',
                          background: env === e ? 'var(--accent)' : 'transparent',
                          color: env === e ? '#fff' : 'var(--text2)', textTransform: 'capitalize',
                        }}>{e === 'all' ? `all (${allPositions.length})` : e === 'paper' ? `paper (${paperCount})` : `real (${allPositions.length - paperCount})`}</button>
                      ))}
                    </div>
                  )}
                  <span style={{ fontSize: 9, color: 'var(--text3)' }}>{positions.length} positions · verified live stops</span>
                </div>
              </div>
              {/* 3-way split (reconciled): VERIFIED (live broker / operator-confirmed) · PLANNED (intended stop,
                  not verified live) · NO STOP. A planned stop is not protection until it's live at the broker. */}
              <div style={{ display: 'flex', height: 32, borderRadius: 6, overflow: 'hidden', marginBottom: 6 }}>
                <div title="Verified: a live broker stop order OR an operator-confirmed stop" style={{ flex: verifiedCount || 0.001, minWidth: verifiedCount ? 84 : 0, background: '#22c55e', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10.5, fontWeight: 700, color: '#06280f', whiteSpace: 'nowrap', overflow: 'hidden' }}>{verifiedCount > 0 ? `${verifiedCount} verified` : ''}</div>
                <div title="Planned: a risk_management stop that is NOT verified live at the broker (advisory)" style={{ flex: plannedOnly || 0.001, minWidth: plannedOnly ? 84 : 0, background: '#f59e0b', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10.5, fontWeight: 700, color: '#1a1205', whiteSpace: 'nowrap', overflow: 'hidden' }}>{plannedOnly > 0 ? `${plannedOnly} planned` : ''}</div>
                <div title="No stop level at all" style={{ flex: noStop.length || 0.001, minWidth: noStop.length ? 84 : 0, background: '#ef4444', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 10.5, fontWeight: 700, color: '#fff', whiteSpace: 'nowrap', overflow: 'hidden' }}>{noStop.length > 0 ? `${noStop.length} no stop` : ''}</div>
              </div>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 8, lineHeight: 1.4 }}>
                <b style={{ color: '#22c55e' }}>verified</b> = live broker stop or operator-confirmed · <b style={{ color: '#f59e0b' }}>planned</b> = intended stop, not yet live at the broker (Schwab/Fidelity stops sit in ToS — confirm to verify) · <b style={{ color: '#ef4444' }}>no stop</b>
              </div>

              {/* Triggered stops — each symbol is individually clickable → its singular stop detail (+ act link) */}
              {triggered.length > 0 && (
                <div id="triggered-stops" style={{ padding: '7px 10px', background: 'rgba(239,68,68,.1)', border: `1px solid ${hlStops ? '#ef4444' : 'rgba(239,68,68,.2)'}`, borderRadius: 6, marginBottom: 6, boxShadow: hlStops ? '0 0 0 2px rgba(239,68,68,.35)' : 'none', scrollMarginTop: 12 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#ef4444', marginBottom: 6 }}>{triggered.length} stops triggered <span style={{ fontSize: 9.5, fontWeight: 500, color: '#fca5a5' }}>— click a symbol to ACT on its stop (arm / ignore 1wk)</span></div>
                  <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
                    {triggered.map((p: any) => (
                      <span key={p.symbol} style={{ display: 'inline-flex', alignItems: 'center' }}>
                        {/* primary: go straight to the actionable Stage 2c card for THIS symbol */}
                        <a href={`/v3/trading?tab=Open%20Trades&symbol=${p.symbol}`} title={`Act on ${p.symbol} — stop $${p.stop_price ?? '—'} (${p.stop_source === 'broker' ? 'LIVE at broker' : p.stop_source === 'confirmed' ? 'operator-confirmed' : 'PLANNED, not live at broker'}) · ${p.distance_to_stop_pct ?? '?'}% past · arm a protective stop or ignore 1 week`}
                          style={{ fontSize: 10.5, fontWeight: 800, fontFamily: 'monospace', padding: '3px 8px', borderRadius: '6px 0 0 6px', textDecoration: 'none', border: '1px solid #ef444466', borderRight: 'none', background: 'rgba(239,68,68,.18)', color: '#fca5a5' }}>{p.symbol} →</a>
                        {/* secondary: read-only review drawer (charts / analyst / finviz) */}
                        <button onClick={() => stopDrill(p)} title={`Review ${p.symbol} (read-only: charts, analyst, finviz)`}
                          style={{ fontSize: 9, fontWeight: 700, padding: '4px 6px', borderRadius: '0 6px 6px 0', cursor: 'pointer', border: '1px solid #ef444466', background: 'rgba(239,68,68,.08)', color: '#fca5a5' }}>ⓘ</button>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* No stop set — each symbol individually clickable */}
              {noStop.length > 0 && (
                <div style={{ padding: '7px 10px', background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.15)', borderRadius: 6 }}>
                  <div style={{ fontSize: 11, color: '#f59e0b', marginBottom: 6 }}>{noStop.length} positions no stop set <span style={{ fontSize: 9.5, color: 'var(--text3)' }}>— click a symbol to arm a protective stop</span></div>
                  <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
                    {noStop.map((p: any) => (
                      <span key={p.symbol} style={{ display: 'inline-flex', alignItems: 'center' }}>
                        <a href={`/v3/trading?tab=Open%20Trades&symbol=${p.symbol}`} title={`Arm a protective stop for ${p.symbol} (no stop set)`}
                          style={{ fontSize: 10.5, fontWeight: 800, fontFamily: 'monospace', padding: '3px 8px', borderRadius: '6px 0 0 6px', textDecoration: 'none', border: '1px solid #f59e0b55', borderRight: 'none', background: 'rgba(245,158,11,.12)', color: '#fcd34d' }}>{p.symbol} →</a>
                        <button onClick={() => stopDrill(p)} title={`Review ${p.symbol} (read-only)`}
                          style={{ fontSize: 9, fontWeight: 700, padding: '4px 6px', borderRadius: '0 6px 6px 0', cursor: 'pointer', border: '1px solid #f59e0b55', background: 'rgba(245,158,11,.06)', color: '#fcd34d' }}>ⓘ</button>
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/risk → positions[], pct_protected, total_risk_dollars</div>
            </div>
          </div>
        </>
      )}

      {tab === 'Regime' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Regime Indicator Heatmap</span>
            <span style={{ fontSize: 9, color: 'var(--text3)' }}>
              {indList.length} indicators · current snapshot · {histList.length} history entries
            </span>
          </div>
          {latest && (
            <div style={{ marginBottom: 12, padding: '6px 10px', borderRadius: 6, background: 'rgba(96,165,250,.06)', fontSize: 11 }}>
              Current regime: <strong style={{ color: signalColor(latest.regime_label === 'risk_off' ? 'risk_off' : latest.regime_label === 'risk_on' ? 'risk_on' : 'neutral') }}>
                {latest.regime_label?.replace(/_/g, ' ')}
              </strong> ({Math.round((latest.confidence ?? 0) * 100)}% confidence)
              {latest.stale_data && <span style={{ color: '#ef4444', marginLeft: 8 }}>STALE DATA</span>}
            </div>
          )}
          {/* Indicator grid — grouped by indicator_group */}
          {indList.length === 0 ? (
            <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20, textAlign: 'center' }}>No regime indicators available</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {indList.map((ind: any, i: number) => (
                <div key={i}
                  onClick={() => onDrill({ title: ind.indicator_key, subtitle: ind.indicator_group, endpoint: '/api/v2/risk-regime/indicators', rows: [ind] })}
                  style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '3px 6px', cursor: 'pointer', borderRadius: 4 }}>
                  <span style={{ width: 140, fontSize: 10, color: 'var(--text2)', fontFamily: 'monospace' }}>{ind.indicator_key}</span>
                  <div style={{ width: 20, height: 16, borderRadius: 3, background: signalColor(ind.signal) }} title={ind.signal} />
                  <span style={{ fontSize: 9, color: 'var(--text3)' }}>{ind.value_text || ind.signal}</span>
                </div>
              ))}
            </div>
          )}
          {/* Regime history timeline */}
          {histList.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text2)', marginBottom: 6 }}>Regime Timeline ({histList.length} snapshots)</div>
              <div style={{ display: 'flex', gap: 2 }}>
                {histList.map((h: any, i: number) => (
                  <div key={i}
                    onClick={() => onDrill({ title: `Regime ${h.regime_label}`, subtitle: h.generated_at?.slice(0, 10), endpoint: '/api/v2/risk-regime/history', rows: [h] })}
                    style={{ flex: 1, height: 20, borderRadius: 3, background: signalColor(h.regime_label === 'risk_on' ? 'risk_on' : h.regime_label === 'risk_off' ? 'risk_off' : 'neutral'), cursor: 'pointer' }}
                    title={`${h.generated_at?.slice(0, 10)}: ${h.regime_label} (${Math.round((h.confidence ?? 0) * 100)}%)`}
                  />
                ))}
              </div>
              <div style={{ display: 'flex', gap: 12, marginTop: 6, fontSize: 9 }}>
                <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: '#22c55e', marginRight: 3 }} />risk-on</span>
                <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: '#f59e0b', marginRight: 3 }} />neutral</span>
                <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: '#ef4444', marginRight: 3 }} />risk-off</span>
              </div>
            </div>
          )}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/risk-regime/indicators + /history (per-indicator-per-day breakdown NOT available — showing current snapshot + overall timeline)</div>
        </div>
      )}

      {tab === 'Correlation' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Correlation Matrix</span>
            <span style={{ fontSize: 9, color: 'var(--text3)' }}>{corrSymbols.length}x{corrSymbols.length} · keyed object</span>
          </div>
          {/* Sector exposure first */}
          {corr?.sector_exposure && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text2)', marginBottom: 6 }}>Sector Exposure</div>
              {Object.entries(corr.sector_exposure).map(([sector, pct]: [string, any]) => (
                <div key={sector} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 2 }}>
                  <span style={{ width: 120, fontSize: 10, color: 'var(--text2)' }}>{sector}</span>
                  <div style={{ flex: 1, height: 14, background: 'var(--bg2)', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: 'rgba(96,165,250,.4)', borderRadius: 3 }} />
                  </div>
                  <span style={{ fontSize: 10, color: 'var(--text0)', width: 40, textAlign: 'right' }}>{pct}%</span>
                </div>
              ))}
            </div>
          )}
          {/* NxN matrix */}
          {corrSymbols.length === 0 ? (
            <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20, textAlign: 'center' }}>Correlation not yet computed</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ borderCollapse: 'collapse', fontSize: 9 }}>
                <thead>
                  <tr>
                    <th style={{ padding: 3 }} />
                    {corrSymbols.map(s => <th key={s} style={{ padding: '3px 6px', color: 'var(--text3)', fontWeight: 400, transform: 'rotate(-45deg)', transformOrigin: 'left bottom' }}>{s}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {corrSymbols.map(row => (
                    <tr key={row}>
                      <td style={{ padding: '3px 6px', color: 'var(--text2)', fontFamily: 'monospace' }}>{row}</td>
                      {corrSymbols.map(col => {
                        const v = corrMatrix[row]?.[col] ?? 0
                        const abs = Math.abs(v)
                        const bg = v >= 0.7 ? 'rgba(239,68,68,.4)' : v >= 0.4 ? 'rgba(245,158,11,.3)' : v <= -0.2 ? 'rgba(59,130,246,.3)' : 'rgba(255,255,255,.03)'
                        return (
                          <td key={col}
                            onClick={() => onDrill({ title: `${row} / ${col}`, subtitle: `Correlation: ${v.toFixed(3)}`, endpoint: '/api/v2/correlation', rows: [{ pair: `${row}/${col}`, correlation: v }] })}
                            style={{ padding: '3px 6px', textAlign: 'center', background: bg, cursor: 'pointer', color: 'var(--text0)', fontFamily: 'monospace' }}>
                            {row === col ? '1.0' : v.toFixed(2)}
                          </td>
                        )
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
              <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6 }}>
                Rate sensitivity: {corr?.rate_sensitivity?.toFixed(2)} — {corr?.rate_interpretation}
              </div>
            </div>
          )}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/correlation → correlation_matrix (keyed object), sector_exposure, rate_sensitivity</div>
        </div>
      )}

      {tab === 'Recovery' && (
        <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Recovery Watch</div>
          {recoveryItems.length === 0 ? (
            <div style={{ color: 'var(--text3)', fontSize: 11, padding: 20, textAlign: 'center' }}>No recovery candidates</div>
          ) : recoveryItems.map((item: any) => (
            <div key={item.id}
              onClick={() => onDrill({ title: `${item.symbol} Recovery`, subtitle: item.analyst_verdict, endpoint: '/api/v2/recovery', rows: [item] })}
              style={{ padding: '10px 10px', borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>{item.symbol}</span> <ProAnalystPill symbol={item.symbol} map={paMap} compact />
                <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4,
                  background: item.analyst_verdict === 'reentry_candidate' ? 'rgba(34,197,94,.1)' : 'rgba(245,158,11,.1)',
                  color: item.analyst_verdict === 'reentry_candidate' ? '#22c55e' : '#f59e0b',
                }}>{item.analyst_verdict?.replace(/_/g, ' ')}</span>
              </div>
              <div style={{ fontSize: 10, color: 'var(--text2)', marginBottom: 4 }}>{item.analyst_summary?.slice(0, 150)}</div>
              <div style={{ fontSize: 9, color: 'var(--text3)' }}>Exit: ${item.exit_price} on {item.stopped_out_at} · {item.reason}</div>
            </div>
          ))}
          <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Source: /api/v2/recovery → items[]</div>
        </div>
      )}
    </div>
  )
}
