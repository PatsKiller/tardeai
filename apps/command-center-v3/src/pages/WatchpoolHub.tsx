import { useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'

// v3 Watchpool & Directives — operator watch directives (ticker/sector/trend) + the unified
// strategy_watchpool, with the shared provenance pill row. Advisory; Hermes-firewall preserved.

interface Props { onDrill: (ctx: DrillContext) => void }

const card = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14 }

// Origin pill palette (per spec): screener=blue, social=orange, agent=green, watchlist=yellow, directive=violet
const originColor = (o?: string) => {
  const k = (o || '').toLowerCase()
  if (k.includes('directive') || k === 'operator' || k === 'hermes' || k === 'trade_ai') return '#a855f7'
  if (k.includes('social')) return '#f59e0b'
  if (k.includes('agent')) return '#22c55e'
  if (k.includes('portfolio') || k.includes('watchlist')) return '#eab308'
  return '#60a5fa'
}
const divColor = (d?: string) => (({ aligned: '#22c55e', mixed: '#f59e0b', divergent: '#ef4444', unavailable: '#64748b' } as any)[d || ''] || 'var(--text3)')

const Pill = ({ text, color, tip }: any) => (
  <span title={tip} style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 4, background: color + '22', color, border: `1px solid ${color}55`, whiteSpace: 'nowrap', cursor: tip ? 'help' : 'default' }}>{text}</span>
)

function Field({ label, value, onChange, ph, wide }: any) {
  return (
    <label style={{ fontSize: 9, color: 'var(--text3)', display: 'flex', flexDirection: 'column', gap: 2 }}>{label}
      <input value={value} onChange={e => onChange(e.target.value)} placeholder={ph}
        style={{ fontSize: 11, padding: '5px 8px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 5, color: 'var(--text0)', width: wide ? 200 : 128 }} />
    </label>
  )
}

export default function WatchpoolHub({ onDrill }: Props) {
  const { data: wd, refetch: refetchWd } = useApi<any>('/api/v2/watch-directives', 60_000)
  const { data: wp, refetch: refetchWp } = useApi<any>('/api/v2/watchpool', 60_000)
  const [kind, setKind] = useState<'ticker' | 'sector' | 'trend'>('ticker')
  const [label, setLabel] = useState('')
  const [field1, setField1] = useState('')
  const [seeds, setSeeds] = useState('')
  const [rationale, setRationale] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const createDirective = async () => {
    setBusy(true); setMsg(null)
    let spec: any = {}
    const syms = (s: string) => s.toUpperCase().split(/[,\s]+/).filter(Boolean)
    if (kind === 'ticker') spec = { symbol: field1.toUpperCase().trim() }
    else if (kind === 'sector') spec = { finviz_sector: field1.trim(), ...(seeds ? { universe: syms(seeds) } : {}) }
    else spec = { keywords: field1.split(',').map(s => s.trim()).filter(Boolean), ...(seeds ? { seed_symbols: syms(seeds) } : {}) }
    try {
      const r = await fetch('/api/v2/watch/directives', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind, label: label || field1, spec, rationale }) })
      const j = await r.json()
      setMsg(j.ok ? `✓ Created directive #${j.directive_id}` : `Error: ${j.error}`)
      if (j.ok) { setLabel(''); setField1(''); setSeeds(''); setRationale(''); refetchWd() }
    } catch (e: any) { setMsg('Error: ' + e.message) }
    setBusy(false)
  }

  const promote = async (symbol: string, directive_id: number) => {
    setBusy(true); setMsg(null)
    try {
      const r = await fetch('/api/v2/watch/directives/promote', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ symbol, directive_id }) })
      const j = await r.json()
      setMsg(j.ok ? `${symbol}: ${j.result?.status}${j.result?.qualified_strategies?.length ? ' → ' + j.result.qualified_strategies.join(', ') : ''}` : `Error: ${j.error}`)
      refetchWd(); refetchWp()
    } catch (e: any) { setMsg('Error: ' + e.message) }
    setBusy(false)
  }

  const directives = wd?.directives ?? []
  const hits = wd?.recent_hits ?? []
  const pool = wp?.rows ?? []

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div>
        <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Watchpool &amp; Directives</div>
        <div style={{ fontSize: 11, color: 'var(--text3)' }}>{wd?.directive_count ?? 0} directives · {wp?.count ?? 0} watchpool entries · advisory · Hermes-firewall preserved (Hermes proposes via staging only)</div>
      </div>

      {/* Add directive */}
      <div style={card}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Add Watch Directive</div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
          {(['ticker', 'sector', 'trend'] as const).map(k => (
            <button key={k} onClick={() => setKind(k)} style={{ padding: '4px 14px', fontSize: 11, borderRadius: 5, border: 'none', cursor: 'pointer', textTransform: 'capitalize', background: kind === k ? 'rgba(168,85,247,.2)' : 'var(--bg2)', color: kind === k ? '#a855f7' : 'var(--text3)', fontWeight: kind === k ? 700 : 400 }}>{k}</button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <Field label={kind === 'ticker' ? 'Symbol' : kind === 'sector' ? 'Finviz Sector' : 'Keywords (comma-sep)'} value={field1} onChange={setField1}
            ph={kind === 'ticker' ? 'RKLB' : kind === 'sector' ? 'Technology' : 'AI datacenter, power'} />
          {kind !== 'ticker' && <Field label={kind === 'sector' ? 'Extra universe (opt)' : 'Seed symbols (opt)'} value={seeds} onChange={setSeeds} ph="NVDA, AMD" />}
          <Field label="Label (opt)" value={label} onChange={setLabel} ph="auto" />
          <Field label="Rationale" value={rationale} onChange={setRationale} ph="thesis" wide />
          <button disabled={busy || !field1} onClick={createDirective} style={{ padding: '7px 16px', fontSize: 11, fontWeight: 700, borderRadius: 6, border: 'none', cursor: busy || !field1 ? 'not-allowed' : 'pointer', background: '#a855f7', color: '#fff', opacity: busy || !field1 ? 0.5 : 1 }}>Create</button>
        </div>
        {msg && <div style={{ fontSize: 10, color: msg.startsWith('Error') ? '#ef4444' : '#22c55e', marginTop: 8 }}>{msg}</div>}
        <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 6 }}>Ticker = exact symbol (auto-evaluated). Sector = ETF + Finviz constituents. Trend = keywords (Hermes discovers → stages). Sector/trend hits stage for one-tap.</div>
      </div>

      {/* Directives + hits + Promote */}
      <div style={card}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Directives</div>
        {directives.length === 0 ? <div style={{ fontSize: 11, color: 'var(--text3)' }}>No directives yet — add one above.</div> :
          directives.map((d: any) => {
            const dhits = hits.filter((h: any) => h.directive_id === d.id)
            return (
              <div key={d.id} style={{ padding: '8px 0', borderBottom: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <Pill text={d.kind} color="#a855f7" />
                  <span style={{ fontWeight: 600, color: 'var(--text0)', fontSize: 12 }}>{d.label}</span>
                  <Pill text={d.status} color={d.status === 'active' ? '#22c55e' : d.status === 'paused' ? '#f59e0b' : 'var(--text3)'} tip={d.status === 'paused' ? 'Auto-paused (cold) — advisory; operator un-pause' : undefined} />
                  <span style={{ fontSize: 9, color: 'var(--text3)' }}>TA {d.trade_ai_enabled ? '✓' : '✗'} · Hermes {d.hermes_enabled ? '✓' : '✗'}</span>
                </div>
                {dhits.length > 0 && (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                    {dhits.slice(0, 14).map((h: any, i: number) => (
                      <span key={i} style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: 10, padding: '2px 6px', borderRadius: 5, background: 'var(--bg2)' }}>
                        <b style={{ fontFamily: 'monospace', color: 'var(--text0)', cursor: 'pointer' }}
                          onClick={() => onDrill({ title: `${h.symbol} — provenance`, subtitle: d.label, endpoint: `/api/v2/watch/provenance/${h.symbol}`, rows: [h] })}>{h.symbol}</b>
                        <Pill text={h.surfaced_by} color={originColor(h.surfaced_by)} />
                        {h.divergence && <Pill text={h.divergence} color={divColor(h.divergence)} tip="internal vs Street" />}
                        <span style={{ fontSize: 8, color: 'var(--text3)' }}>{(h.promotion_status || '').replace(/_/g, ' ').toLowerCase()}</span>
                        {h.promotion_status === 'STAGED_FOR_REVIEW' && (
                          <button onClick={() => promote(h.symbol, d.id)} disabled={busy}
                            style={{ fontSize: 8, fontWeight: 700, padding: '2px 7px', borderRadius: 3, border: 'none', cursor: busy ? 'wait' : 'pointer', background: '#22c55e', color: '#fff' }}>Promote</button>
                        )}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
      </div>

      {/* Unified watchpool */}
      <div style={card}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Watchpool
          <span style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 400, marginLeft: 8 }}>
            {Object.entries(wp?.by_status ?? {}).map(([k, v]: any) => `${v} ${String(k).toLowerCase()}`).join(' · ')}
          </span>
        </div>
        {pool.length === 0 ? <div style={{ fontSize: 11, color: 'var(--text3)' }}>Watchpool empty.</div> : (<>
          <div style={{ display: 'flex', fontSize: 9, color: 'var(--text3)', padding: '0 6px 4px', textTransform: 'uppercase', letterSpacing: 0.3 }}>
            <span style={{ flex: '0 0 64px' }}>Symbol</span><span style={{ flex: '0 0 160px' }}>Strategy</span><span style={{ flex: '0 0 96px' }}>Bucket</span><span style={{ flex: '0 0 70px' }}>Status</span><span style={{ flex: '1 1 auto' }}>Origin</span>
          </div>
          {pool.slice(0, 60).map((r: any) => (
            <div key={r.id} onClick={() => onDrill({ title: `${r.symbol} — provenance`, subtitle: `${r.strategy_id} · ${r.bucket}`, endpoint: `/api/v2/watch/provenance/${r.symbol}`, rows: [r] })}
              style={{ display: 'flex', alignItems: 'center', padding: '4px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11 }}>
              <span style={{ flex: '0 0 64px', fontWeight: 600, fontFamily: 'monospace', color: 'var(--text0)' }}>{r.symbol}</span>
              <span style={{ flex: '0 0 160px', color: 'var(--text2)', fontSize: 10 }}>{r.strategy_id}</span>
              <span style={{ flex: '0 0 96px' }}><Pill text={r.bucket || '?'} color="#60a5fa" /></span>
              <span style={{ flex: '0 0 70px', color: 'var(--text2)', fontSize: 10 }}>{r.current_status}</span>
              <span style={{ flex: '1 1 auto', display: 'flex', gap: 5, alignItems: 'center' }}>
                <Pill text={r.origin_system || 'screener'} color={originColor(r.origin_system)} />
                {r.directive_label && <span style={{ fontSize: 9, color: '#a855f7' }}>◆ {r.directive_label}</span>}
              </span>
            </div>
          ))}
        </>)}
        <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Click a row for full provenance (origin · tier · Street consensus · divergence). Advisory — promotion is gated; no execution.</div>
      </div>
    </div>
  )
}
