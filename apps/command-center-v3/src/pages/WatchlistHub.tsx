import { useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import ProAnalystPill, { useProAnalystMap } from '../components/ProAnalystPill'

interface Props { onDrill: (ctx: DrillContext) => void }

const card: React.CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }
const advColor = (f?: string) => f === 'caution' ? '#ef4444' : f === 'favorable' ? '#22c55e' : 'var(--text3)'
const trendColor = (t?: string) => (t || '').toLowerCase().includes('up') ? '#22c55e' : (t || '').toLowerCase().includes('down') ? '#ef4444' : 'var(--text2)'

// ── provenance pill palette (origin=violet for directives; reuse across the page) ──
const originColor = (o?: string) => {
  const k = (o || '').toLowerCase()
  if (k.includes('directive') || k === 'operator') return '#a855f7'
  if (k === 'hermes') return '#14b8a6'
  if (k.includes('social')) return '#f59e0b'
  if (k.includes('agent')) return '#22c55e'
  if (k.includes('portfolio')) return '#eab308'
  return '#60a5fa'
}
const originLabel = (o?: string) => ({ trade_ai_screener: 'Screener', agent_discovery: 'AI', operator: 'Operator', hermes: 'Hermes', portfolio: 'Portfolio', social: 'Social' } as any)[o || ''] || (o || 'screener')
const tierColor = (t?: string) => (({ core: '#22c55e', trusted: '#84cc16', probationary: '#f59e0b', candidate: '#94a3b8', demoted: '#ef4444' } as any)[t || ''] || 'var(--text3)')

const Pill = ({ text, color, tip }: any) => (
  <span title={tip} style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 4, background: color + '22', color, border: `1px solid ${color}55`, whiteSpace: 'nowrap', cursor: tip ? 'help' : 'default' }}>{text}</span>
)

const ORIGIN_OPTS = [['all', 'All'], ['trade_ai_screener', 'Screener'], ['agent_discovery', 'AI-discovered'], ['operator', 'Operator-directive'], ['hermes', 'Hermes'], ['portfolio', 'Portfolio']]
const SEL: React.CSSProperties = { fontSize: 11, padding: '5px 8px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 5, color: 'var(--text0)' }

export default function WatchlistHub({ onDrill }: Props) {
  const { data: wl, refetch: refetchWl } = useApi<any>('/api/v2/watchlist/items?status=active', 60_000)
  const { data: summary } = useApi<any>('/api/v2/watchlist/summary', 120_000)
  const { data: adv } = useApi<any>('/api/v2/setup-advisory/candidates?entity=watchlist', 120_000)
  const { data: wd, refetch: refetchWd } = useApi<any>('/api/v2/watch-directives', 60_000)
  const paMap = useProAnalystMap()

  const [fOrigin, setFOrigin] = useState('all')
  const [fBand, setFBand] = useState('all')
  const [fKind, setFKind] = useState('all')   // all | directive
  const [fDir, setFDir] = useState('all')
  const [search, setSearch] = useState('')
  const [showAdd, setShowAdd] = useState(false)

  const items: any[] = wl?.items ?? []
  const advMap: Record<string, any> = {}
  for (const a of (adv?.advisories ?? [])) advMap[a.symbol] = a
  const advisories: any[] = adv?.advisories ?? []
  const cautionN = advisories.filter(a => a.advisory_flag === 'caution').length
  const favorableN = advisories.filter(a => a.advisory_flag === 'favorable').length
  const byStatus = summary?.by_status ?? {}
  const directives: any[] = wd?.directives ?? []
  const sectorTrendDirs = directives.filter(d => d.kind === 'sector' || d.kind === 'trend')

  const visible = useMemo(() => items.filter(it => {
    if (fOrigin !== 'all' && it.origin_system !== fOrigin) return false
    if (fKind === 'directive' && !it.directive_id) return false
    if (fDir !== 'all' && String(it.directive_id) !== fDir) return false
    if (fBand !== 'all') { const b = advMap[it.symbol]?.advisory_flag || 'none'; if (b !== fBand) return false }
    if (search && !String(it.symbol).toUpperCase().includes(search.toUpperCase())) return false
    return true
  }), [items, fOrigin, fKind, fDir, fBand, search])

  const freshness = (it: any) => it.bucket ? it.bucket : (it.in_directive_watch ? 'standing' : '')

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Watchlist</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{byStatus.active ?? items.length} active · {byStatus.researched ?? 0} researched · {byStatus.removed ?? 0} removed</div>
        </div>
        <button onClick={() => setShowAdd(true)} style={{ padding: '8px 16px', fontSize: 12, fontWeight: 700, borderRadius: 7, border: 'none', cursor: 'pointer', background: '#a855f7', color: '#fff' }}>+ Add Watch</button>
      </div>

      {/* advisory strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10, marginBottom: 14 }}>
        {[
          { label: 'Active items', value: items.length, color: 'var(--text0)' },
          { label: 'With setup advisory', value: advisories.length, color: '#60a5fa' },
          { label: '⚠ Caution band', value: cautionN, color: '#ef4444' },
          { label: 'Favorable band', value: favorableN, color: '#22c55e' },
        ].map(k => (
          <div key={k.label} style={{ ...card, textAlign: 'center' }}>
            <div style={{ fontSize: 24, fontWeight: 700, color: k.color }}>{k.value}</div>
            <div style={{ fontSize: 10, color: 'var(--text3)', marginTop: 4 }}>{k.label}</div>
          </div>
        ))}
      </div>

      {/* Sectors / Directives (first-class) */}
      {directives.length > 0 && (
        <div style={{ ...card, marginBottom: 14 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Watch Directives <span style={{ fontSize: 9, color: 'var(--text3)', fontWeight: 400 }}>· operator standing instructions (Trade AI + Hermes honor; Hermes proposes via staging)</span></div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {directives.map(d => {
              const dhits = (wd?.recent_hits ?? []).filter((h: any) => h.directive_id === d.id)
              return (
                <div key={d.id} onClick={() => setFDir(String(d.id))} title="filter the list to this directive's hits"
                  style={{ padding: '6px 10px', background: 'var(--bg2)', borderRadius: 8, cursor: 'pointer', border: fDir === String(d.id) ? '1px solid #a855f7' : '1px solid var(--border)' }}>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <Pill text={d.kind} color="#a855f7" />
                    <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--text0)' }}>{d.label}</span>
                    <Pill text={d.status} color={d.status === 'active' ? '#22c55e' : d.status === 'paused' ? '#f59e0b' : 'var(--text3)'} tip={d.status === 'paused' ? 'auto-paused (cold) — advisory; operator un-pause' : undefined} />
                  </div>
                  <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 3 }}>{dhits.length} hits · {dhits.filter((h: any) => h.promotion_status === 'STAGED_FOR_REVIEW').length} staged</div>
                </div>
              )
            })}
          </div>
          {sectorTrendDirs.length === 0 && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6 }}>No sector/trend directives yet — use “+ Add Watch”.</div>}
        </div>
      )}

      {/* Filter bar */}
      <div style={{ ...card, marginBottom: 12, display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <label style={{ fontSize: 9, color: 'var(--text3)', display: 'flex', flexDirection: 'column', gap: 2 }}>Origin
          <select style={SEL} value={fOrigin} onChange={e => setFOrigin(e.target.value)}>{ORIGIN_OPTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label style={{ fontSize: 9, color: 'var(--text3)', display: 'flex', flexDirection: 'column', gap: 2 }}>Advisory band
          <select style={SEL} value={fBand} onChange={e => setFBand(e.target.value)}><option value="all">All</option><option value="favorable">Favorable</option><option value="caution">Caution</option><option value="none">None</option></select></label>
        <label style={{ fontSize: 9, color: 'var(--text3)', display: 'flex', flexDirection: 'column', gap: 2 }}>Kind
          <select style={SEL} value={fKind} onChange={e => setFKind(e.target.value)}><option value="all">All</option><option value="directive">Directive-sourced</option></select></label>
        <label style={{ fontSize: 9, color: 'var(--text3)', display: 'flex', flexDirection: 'column', gap: 2 }}>Directive
          <select style={SEL} value={fDir} onChange={e => setFDir(e.target.value)}><option value="all">All</option>{directives.map(d => <option key={d.id} value={String(d.id)}>{d.label}</option>)}</select></label>
        <label style={{ fontSize: 9, color: 'var(--text3)', display: 'flex', flexDirection: 'column', gap: 2 }}>Search
          <input style={SEL} value={search} onChange={e => setSearch(e.target.value)} placeholder="symbol" /></label>
        <div style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text3)' }}>{visible.length} / {items.length} shown</div>
      </div>

      <div style={{ fontSize: 10, color: '#f59e0b', marginBottom: 12, padding: '8px 12px', background: 'rgba(245,158,11,.06)', border: '1px solid rgba(245,158,11,.2)', borderRadius: 6 }}>
        ⚠ {adv?.disclaimer ?? 'Advisory only — current technical posture vs the post-trade prior. Never gates promotion/scoring.'}
      </div>

      {/* table with provenance pills */}
      <div style={card}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Watchlist ({visible.length})</div>
        {visible.length === 0 ? (
          <div style={{ color: 'var(--text3)', fontSize: 12, padding: 16 }}>No items match the filters.</div>
        ) : (
          <div style={{ maxHeight: 540, overflowY: 'auto' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '0.9fr 1.9fr 0.6fr 0.7fr 1.3fr', fontSize: 9, color: 'var(--text3)', padding: '4px 6px', borderBottom: '1px solid var(--border)', textTransform: 'uppercase' }}>
              <span>Symbol</span><span>Provenance</span><span>Score</span><span>Trend</span><span>Setup advisory</span>
            </div>
            {visible.slice(0, 250).map((it: any) => {
              const a = advMap[it.symbol]
              const fr = freshness(it)
              return (
                <div key={it.id}
                  onClick={() => onDrill({ title: it.symbol, subtitle: `${it.origin_system ?? it.source ?? ''} · ${it.bucket ?? ''} · ${it.status}`, endpoint: `/api/v2/watch/provenance/${it.symbol}`,
                    rows: [a ? { ...it, setup_advisory: a.note, setup_advisory_flag: a.advisory_flag, current_rsi: a.rsi, rsi_band: a.band } : it] })}
                  style={{ display: 'grid', gridTemplateColumns: '0.9fr 1.9fr 0.6fr 0.7fr 1.3fr', padding: '7px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, alignItems: 'center' }}>
                  <span style={{ fontWeight: 600, color: 'var(--text0)', fontFamily: 'monospace' }}>{it.symbol} <ProAnalystPill symbol={it.symbol} map={paMap} compact /></span>
                  <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
                    <Pill text={originLabel(it.origin_system)} color={originColor(it.origin_system)} tip={it.provenance_reason || it.source} />
                    {it.source_tier && <Pill text={it.source_tier} color={tierColor(it.source_tier)} />}
                    {fr && <Pill text={fr} color="#60a5fa" tip="bucket / TTL" />}
                    {it.directive_id && <Pill text="◆ directive" color="#a855f7" tip="from an operator watch directive" />}
                  </span>
                  <span style={{ color: 'var(--text2)' }}>{it.score != null ? Number(it.score).toFixed(0) : '—'}</span>
                  <span style={{ color: trendColor(it.trend), fontSize: 10 }}>{it.trend ?? '—'}</span>
                  <span>
                    {a ? (
                      <span title={a.note} style={{ fontSize: 9, padding: '2px 7px', borderRadius: 4, background: 'var(--bg2)', color: advColor(a.advisory_flag), border: `1px solid ${advColor(a.advisory_flag)}33` }}>
                        {a.advisory_flag === 'caution' ? '⚠ ' : ''}RSI {Number(a.rsi).toFixed(0)} ({a.band})
                      </span>
                    ) : <span style={{ color: 'var(--text3)', fontSize: 9 }}>—</span>}
                  </span>
                </div>
              )
            })}
          </div>
        )}
        <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Click a row → full provenance (origin · tier · Street consensus · divergence). Advisory-only — read-only, never gates.</div>
      </div>

      {showAdd && <AddWatchModal onClose={() => setShowAdd(false)} onCreated={() => { refetchWd(); refetchWl() }} paMap={paMap} />}
    </div>
  )
}

// ── Full-circle Add-Watch modal: entry → resolution → preview → save ──
function AddWatchModal({ onClose, onCreated, paMap }: { onClose: () => void; onCreated: () => void; paMap: any }) {
  const { data: sectorsData } = useApi<any>('/api/v2/watch/sectors', 600_000)
  const [kind, setKind] = useState<'ticker' | 'sector' | 'trend'>('ticker')
  const [symbol, setSymbol] = useState('')
  const [sector, setSector] = useState('')
  const [keywords, setKeywords] = useState('')
  const [seeds, setSeeds] = useState('')
  const [label, setLabel] = useState('')
  const [rationale, setRationale] = useState('')
  const [priority, setPriority] = useState('normal')
  const [taOn, setTaOn] = useState(true)
  const [hermesOn, setHermesOn] = useState(true)
  const [ttl, setTtl] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const sectors: any[] = sectorsData?.sectors ?? []
  const selSector = sectors.find(s => s.sector === sector)
  const div = (paMap?.[(symbol || '').toUpperCase()]?.divergence) as string | undefined
  const governor = kind === 'ticker'
    ? `Operator-named ticker → evaluated immediately (scalp firewall still applies)${div ? ` · current Street divergence: ${div}` : ''}`
    : 'Resolved symbols stage for your one-tap promote (core/trusted + not divergent would auto-promote)'

  const fld: React.CSSProperties = { fontSize: 11, padding: '6px 9px', background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 5, color: 'var(--text0)', width: '100%' }
  const lbl: React.CSSProperties = { fontSize: 9, color: 'var(--text3)', display: 'block', marginBottom: 3 }

  const save = async () => {
    setBusy(true); setMsg(null)
    const syms = (s: string) => s.toUpperCase().split(/[,\s]+/).filter(Boolean)
    let spec: any = {}, autoLabel = label
    if (kind === 'ticker') { spec = { symbol: symbol.toUpperCase().trim() }; autoLabel = label || `watch ${symbol.toUpperCase().trim()}` }
    else if (kind === 'sector') { spec = { finviz_sector: sector }; autoLabel = label || `sector ${sector}` }
    else { spec = { keywords: keywords.split(',').map(s => s.trim()).filter(Boolean), ...(seeds ? { seed_symbols: syms(seeds) } : {}) }; autoLabel = label || `trend ${keywords.slice(0, 30)}` }
    try {
      const r = await fetch('/api/v2/watch/directives', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind, label: autoLabel, spec, rationale, priority, ttl_days: ttl ? Number(ttl) : null, trade_ai_enabled: taOn, hermes_enabled: hermesOn }),
      })
      const j = await r.json()
      if (j.ok) { setMsg(`✓ Created directive #${j.directive_id}`); onCreated(); setTimeout(onClose, 900) }
      else setMsg(`Error: ${j.error}`)
    } catch (e: any) { setMsg('Error: ' + e.message) }
    setBusy(false)
  }

  const canSave = kind === 'ticker' ? !!symbol.trim() : kind === 'sector' ? !!sector : !!keywords.trim()

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
      <div onClick={e => e.stopPropagation()} style={{ ...card, width: 520, maxWidth: '92vw', maxHeight: '88vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text0)' }}>Add Watch Directive</div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text3)', cursor: 'pointer', fontSize: 16 }}>✕</button>
        </div>

        {/* kind selector */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>
          {(['ticker', 'sector', 'trend'] as const).map(k => (
            <button key={k} onClick={() => setKind(k)} style={{ flex: 1, padding: '6px 0', fontSize: 11, borderRadius: 6, border: 'none', cursor: 'pointer', textTransform: 'capitalize', background: kind === k ? 'rgba(168,85,247,.2)' : 'var(--bg2)', color: kind === k ? '#a855f7' : 'var(--text3)', fontWeight: kind === k ? 700 : 400 }}>{k}</button>
          ))}
        </div>

        {/* kind-specific */}
        {kind === 'ticker' && (
          <div style={{ marginBottom: 10 }}><label style={lbl}>Symbol</label>
            <input style={fld} value={symbol} onChange={e => setSymbol(e.target.value.toUpperCase())} placeholder="RKLB" autoFocus /></div>
        )}
        {kind === 'sector' && (
          <div style={{ marginBottom: 10 }}><label style={lbl}>Sector (Finviz/GICS)</label>
            <select style={fld} value={sector} onChange={e => setSector(e.target.value)}>
              <option value="">— select sector —</option>
              {sectors.map(s => <option key={s.sector} value={s.sector}>{s.sector} ({s.count})</option>)}
            </select>
            {selSector && (
              <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6, padding: '6px 8px', background: 'var(--bg2)', borderRadius: 5 }}>
                Resolves to the sector ETF + up to 25 of <b style={{ color: 'var(--text2)' }}>{selSector.count}</b> constituents (capped).
                First: <span style={{ fontFamily: 'monospace', color: 'var(--text2)' }}>{(selSector.sample || []).join(', ')}</span>
              </div>
            )}
          </div>
        )}
        {kind === 'trend' && (<>
          <div style={{ marginBottom: 10 }}><label style={lbl}>Keywords (comma-sep)</label>
            <input style={fld} value={keywords} onChange={e => setKeywords(e.target.value)} placeholder="AI datacenter, power" autoFocus /></div>
          <div style={{ marginBottom: 10 }}><label style={lbl}>Seed symbols (optional)</label>
            <input style={fld} value={seeds} onChange={e => setSeeds(e.target.value)} placeholder="NVDA, VRT" /></div>
          <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 10 }}>Hermes owns discovery — it proposes symbols into staging; the app drains + evaluates them.</div>
        </>)}

        {/* shared */}
        <div style={{ marginBottom: 10 }}><label style={lbl}>Label (optional)</label><input style={fld} value={label} onChange={e => setLabel(e.target.value)} placeholder="auto" /></div>
        <div style={{ marginBottom: 10 }}><label style={lbl}>Rationale / thesis</label><input style={fld} value={rationale} onChange={e => setRationale(e.target.value)} placeholder="why watch this" /></div>
        <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
          <label style={{ flex: 1, ...lbl }}>Priority<select style={fld} value={priority} onChange={e => setPriority(e.target.value)}><option value="normal">normal</option><option value="high">high</option></select></label>
          <label style={{ flex: 1, ...lbl }}>TTL days (blank = standing)<input style={fld} value={ttl} onChange={e => setTtl(e.target.value.replace(/\D/g, ''))} placeholder="standing" /></label>
        </div>
        <div style={{ display: 'flex', gap: 16, marginBottom: 12, fontSize: 11, color: 'var(--text2)' }}>
          <label style={{ cursor: 'pointer' }}><input type="checkbox" checked={taOn} onChange={e => setTaOn(e.target.checked)} /> Trade AI</label>
          <label style={{ cursor: 'pointer' }}><input type="checkbox" checked={hermesOn} onChange={e => setHermesOn(e.target.checked)} /> Hermes</label>
        </div>

        {/* governor preview */}
        <div style={{ fontSize: 9, color: 'var(--text3)', marginBottom: 12, padding: '7px 9px', background: 'var(--bg2)', borderRadius: 5, borderLeft: '3px solid #a855f7' }}>
          <b style={{ color: 'var(--text2)' }}>How it promotes:</b> {governor}
        </div>

        {msg && <div style={{ fontSize: 11, color: msg.startsWith('Error') ? '#ef4444' : '#22c55e', marginBottom: 10 }}>{msg}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ padding: '8px 14px', fontSize: 11, borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text2)', cursor: 'pointer' }}>Cancel</button>
          <button disabled={busy || !canSave} onClick={save} style={{ padding: '8px 18px', fontSize: 11, fontWeight: 700, borderRadius: 6, border: 'none', background: '#a855f7', color: '#fff', cursor: busy || !canSave ? 'not-allowed' : 'pointer', opacity: busy || !canSave ? 0.5 : 1 }}>Save Directive</button>
        </div>
      </div>
    </div>
  )
}
