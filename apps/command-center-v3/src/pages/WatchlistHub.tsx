import { useState, useMemo } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import ProAnalystPill, { useProAnalystMap } from '../components/ProAnalystPill'
import DiscoveryPanel from '../components/DiscoveryPanel'
import ToSWatchlists from '../components/ToSWatchlists'

interface Props { onDrill: (ctx: DrillContext) => void }

const card: React.CSSProperties = { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16 }
const advColor = (f?: string) => f === 'caution' ? '#ef4444' : f === 'favorable' ? '#22c55e' : 'var(--text3)'
const trendColor = (t?: string) => (t || '').toLowerCase().includes('up') ? '#22c55e' : (t || '').toLowerCase().includes('down') ? '#ef4444' : 'var(--text2)'
const trendBadge = (t?: string) => (({ bullish: '#22c55e', bearish: '#ef4444', neutral: '#f59e0b', unknown: 'var(--text3)' } as any)[(t || '').toLowerCase()] || 'var(--text3)')
// external-LLM curation badge meta (which LLM enhanced this name)
const llmMeta = (lane?: string) => (({ grok: { label: 'Grok', color: '#1d9bf0' }, chatgpt: { label: 'ChatGPT', color: '#10a37f' }, claude: { label: 'Claude', color: '#d97757' } } as any)[lane || ''] || { label: lane || 'LLM', color: 'var(--text3)' })

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
  // Show the real watchlist (active + researched), ranked by the Hermes composite score (highest first).
  const { data: wl, refetch: refetchWl } = useApi<any>('/api/v2/watchlist/items?sort=hermes', 60_000)
  const { data: summary } = useApi<any>('/api/v2/watchlist/summary', 120_000)
  const { data: adv } = useApi<any>('/api/v2/setup-advisory/candidates?entity=watchlist', 120_000)
  const { data: wd, refetch: refetchWd } = useApi<any>('/api/v2/watch-directives', 60_000)
  const { data: ext, refetch: refetchExt } = useApi<any>('/api/v2/hermes/external-intel-map', 60_000)
  const extMap: Record<string, any[]> = ext?.map ?? {}
  // unified card layer: description / sector vs-sector / analyst / top-3 news (operator 2026-06-12)
  const { data: scards } = useApi<any>('/api/v2/symbol-cards', 300_000)
  const cardMap: Record<string, any> = (scards as any)?.cards ?? {}
  const { data: curateStatus, refetch: refetchCurate } = useApi<any>('/api/v2/hermes/curate-top20', 20_000)
  const curateRunning = !!curateStatus?.running
  const runChatgptTop20 = async () => {
    if (curateRunning) return
    try {
      await fetch('/api/v2/hermes/curate-top20', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lanes: 'chatgpt' }) })
      setTimeout(() => { refetchCurate(); refetchExt() }, 1500)
    } catch { /* advisory */ }
  }
  const paMap = useProAnalystMap()

  const [fOrigin, setFOrigin] = useState('all')
  const [fBand, setFBand] = useState('all')
  const [fKind, setFKind] = useState('all')   // all | directive
  const [fDir, setFDir] = useState('all')
  const [fStatus, setFStatus] = useState('all')   // all (active+researched) | active | researched
  const [fRating, setFRating] = useState('all')   // analyst-rating filter (operator 2026-06-12)
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

  const visible = useMemo(() => {
    const seen = new Set<string>()
    return items.filter(it => {
      if (seen.has(it.symbol)) return false   // dedup: watchlist_items can hold multiple rows per symbol
      if (fStatus !== 'all' && it.status !== fStatus) return false
      // "Operator-directive" matches directive-linked items too (AI-discovered first then put under a
      // directive keeps origin_system=agent_discovery, but it IS operator-directed via directive_id).
      if (fOrigin !== 'all') {
        if (fOrigin === 'operator') { if (!it.directive_id && it.origin_system !== 'operator') return false }
        else if (it.origin_system !== fOrigin) return false
      }
      if (fKind === 'directive' && !it.directive_id) return false
      if (fDir !== 'all' && String(it.directive_id) !== fDir) return false
      if (fBand !== 'all') { const b = advMap[it.symbol]?.advisory_flag || 'none'; if (b !== fBand) return false }
      if (fRating !== 'all') {
        const rec = paMap[it.symbol]?.rec || 'no_coverage'
        if (fRating === 'buy_plus' ? !['strong_buy', 'buy'].includes(rec) : rec !== fRating) return false
      }
      if (search && !String(it.symbol).toUpperCase().includes(search.toUpperCase())) return false
      seen.add(it.symbol)
      return true
    })
  }, [items, fOrigin, fKind, fDir, fBand, fStatus, fRating, search, paMap])

  const freshness = (it: any) => it.bucket ? it.bucket : (it.in_directive_watch ? 'standing' : '')

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Watchlist</div>
          <div style={{ fontSize: 11, color: 'var(--text3)' }}>{byStatus.active ?? items.length} active · {byStatus.researched ?? 0} researched · {byStatus.removed ?? 0} removed</div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button onClick={runChatgptTop20} disabled={curateRunning} title="Run the free ChatGPT (codex OAuth) curation on the top-20 ranked names. Grok runs automatically every 2h; this is the optional manual ChatGPT pass."
            style={{ padding: '8px 14px', fontSize: 12, fontWeight: 700, borderRadius: 7, border: '1px solid #10a37f', cursor: curateRunning ? 'default' : 'pointer', background: curateRunning ? 'rgba(16,163,127,.15)' : 'rgba(16,163,127,.12)', color: '#10a37f', opacity: curateRunning ? 0.7 : 1 }}>
            {curateRunning ? `✦ ChatGPT running… ${curateStatus?.chatgpt_curated_top20 ?? 0}/20` : '✦ Run ChatGPT on Top 20'}
          </button>
          <button onClick={() => setShowAdd(true)} style={{ padding: '8px 16px', fontSize: 12, fontWeight: 700, borderRadius: 7, border: 'none', cursor: 'pointer', background: '#a855f7', color: '#fff' }}>+ Add Watch</button>
        </div>
      </div>

      {/* advisory strip */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 10, marginBottom: 14 }}>
        {[
          { label: 'Watchlist items', value: items.length, color: 'var(--text0)' },
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

      {/* Discovery & Watchlist Builder */}
      <DiscoveryPanel onAdded={refetchWl} />
      <ToSWatchlists />

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
        <label style={{ fontSize: 9, color: 'var(--text3)', display: 'flex', flexDirection: 'column', gap: 2 }}>Status
          <select style={SEL} value={fStatus} onChange={e => setFStatus(e.target.value)}><option value="all">Active + Researched</option><option value="active">Active only</option><option value="researched">Researched only</option></select></label>
        <label style={{ fontSize: 9, color: 'var(--text3)', display: 'flex', flexDirection: 'column', gap: 2 }}>Origin
          <select style={SEL} value={fOrigin} onChange={e => setFOrigin(e.target.value)}>{ORIGIN_OPTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label style={{ fontSize: 9, color: 'var(--text3)', display: 'flex', flexDirection: 'column', gap: 2 }}>Advisory band
          <select style={SEL} value={fBand} onChange={e => setFBand(e.target.value)}><option value="all">All</option><option value="favorable">Favorable</option><option value="caution">Caution</option><option value="none">None</option></select></label>
        {/* analyst-rating filter pills (operator 2026-06-12) */}
        <label style={{ fontSize: 9, color: 'var(--text3)', display: 'flex', flexDirection: 'column', gap: 2 }}>Analyst rating
          <span style={{ display: 'flex', gap: 4 }}>
            {[['all', 'All', 'var(--text3)'], ['strong_buy', 'Strong Buy', '#22c55e'], ['buy_plus', 'Buy+', '#86efac'],
              ['hold', 'Hold', '#f59e0b'], ['no_coverage', 'No coverage', 'var(--text3)']].map(([k, lbl, c]) => (
              <button key={k} onClick={() => setFRating(k as string)} style={{
                fontSize: 9.5, padding: '4px 9px', borderRadius: 5, cursor: 'pointer',
                border: `1px solid ${fRating === k ? c : 'var(--border)'}`,
                background: fRating === k ? `color-mix(in srgb, ${c} 16%, transparent)` : 'var(--bg2)',
                color: fRating === k ? (c as string) : 'var(--text3)', fontWeight: fRating === k ? 700 : 400,
              }}>{lbl}</button>
            ))}
          </span></label>
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

      {/* holdings-style card grid (E-2) — enriched data + provenance pills */}
      <div style={card}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Watchlist ({visible.length})</div>
        {visible.length === 0 ? (
          <div style={{ color: 'var(--text3)', fontSize: 12, padding: 16 }}>No items match the filters.</div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))', gap: 12, maxHeight: 640, overflowY: 'auto' }}>
            {visible.slice(0, 200).map((it: any) => {
              const a = advMap[it.symbol]
              const fr = freshness(it)
              const enriched = !!it.last_enriched_at
              const stale = enriched && (Date.now() - new Date(it.last_enriched_at).getTime()) > 2 * 3600 * 1000
              const rsi = it.rsi != null ? Number(it.rsi) : null
              const tcol = trendBadge(it.trend)
              return (
                <div key={it.id}
                  onClick={() => onDrill({ title: `${it.symbol}${it.hermes_rank != null ? ` — Hermes #${it.hermes_rank} (${it.hermes_composite_score})` : ''}`, subtitle: `${it.origin_system ?? it.source ?? ''} · ${it.status}`, endpoint: `/api/v2/hermes/intel/${it.symbol}`,
                    rows: [a ? { ...it, setup_advisory_note: a.note, setup_advisory_flag: a.advisory_flag, current_rsi: a.rsi, rsi_band: a.band } : it] })}
                  style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderLeft: `3px solid ${it.directive_id ? '#a855f7' : originColor(it.origin_system)}`, borderRadius: 9, padding: 10, cursor: 'pointer', display: 'flex', flexDirection: 'column', gap: 7 }}>
                  {/* header: symbol + price */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                    <span style={{ fontWeight: 700, color: 'var(--text0)', fontFamily: 'monospace', fontSize: 13 }}>
                      {it.hermes_rank != null && <span title={`Hermes composite ${it.hermes_composite_score} · confidence ${it.hermes_score_components?._confidence ?? '—'} · coverage ${it.hermes_score_components?._coverage ?? '—'}`}
                        style={{ fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 4, background: 'rgba(168,85,247,.18)', color: '#c084fc', marginRight: 6, cursor: 'help' }}>★#{it.hermes_rank} · {Number(it.hermes_composite_score).toFixed(0)}</span>}
                      {it.symbol} <ProAnalystPill symbol={it.symbol} map={paMap} compact /></span>
                    <span style={{ textAlign: 'right' }}>
                      <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text1)' }}>{it.price != null ? `$${Number(it.price).toFixed(2)}` : ''}</span>
                      {it.change_pct != null && <span style={{ fontSize: 10, marginLeft: 5, color: Number(it.change_pct) >= 0 ? '#22c55e' : '#ef4444' }}>{Number(it.change_pct) >= 0 ? '+' : ''}{Number(it.change_pct).toFixed(2)}%</span>}
                    </span>
                  </div>
                  {/* provenance pills */}
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
                    <Pill text={originLabel(it.origin_system)} color={originColor(it.origin_system)} tip={it.provenance_reason || it.source} />
                    {it.source_tier && <Pill text={it.source_tier} color={tierColor(it.source_tier)} />}
                    {fr && <Pill text={fr} color="#60a5fa" tip="bucket / TTL" />}
                    {it.directive_id && <Pill text="◆ directive" color="#a855f7" tip={it.provenance_reason || 'from an operator watch directive'} />}
                    {it.in_portfolio && <Pill text="💼 HELD" color="#ffa726" tip="this watchlist symbol is also a current portfolio holding — see Portfolio hub for position/basis" />}
                    {/* entry plan chip (operator 2026-06-12: actionable plans, not just analysis) */}
                    {it.entry_urgency && (
                      <Pill text={`🎯 ${it.entry_urgency === 'ready' ? 'READY' : it.entry_urgency === 'near_entry' ? 'NEAR-ENTRY' : 'planned'} · ${it.entry_setup} · zone ${Number(it.entry_zone_low).toFixed(2)}–${Number(it.entry_zone_high).toFixed(2)} · lim ${Number(it.entry_limit).toFixed(2)}`}
                        color={it.entry_urgency === 'ready' ? '#22c55e' : it.entry_urgency === 'near_entry' ? '#f59e0b' : 'var(--text3)'}
                        tip={`ENTRY PLAN (advisory only — nothing queued/executed)\nstop ${it.entry_stop} · target ${it.entry_target} · R:R ${it.entry_rr}\nproposal advice: ${it.entry_tag} · confidence ${it.entry_confidence}\nplanned ${String(it.entry_planned_at).slice(0, 16).replace('T', ' ')} by ${it.entry_model}`} />
                    )}
                    {(extMap[it.symbol] || []).map((e: any, i: number) => {
                      const m = llmMeta(e.lane)
                      return <Pill key={`llm${i}`} text={`✦ ${m.label}`} color={m.color}
                        tip={`Curated by ${m.label}${e.recommendation ? ` — ${e.recommendation}` : ''}\n${e.at ? new Date(e.at).toLocaleString() : ''}`} />
                    })}
                  </div>
                  {/* enriched badges OR awaiting state */}
                  {!enriched ? (
                    <div style={{ fontSize: 10, color: 'var(--text3)', fontStyle: 'italic' }}>awaiting enrichment…</div>
                  ) : (
                    <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
                      {rsi != null && <Pill text={`RSI ${rsi.toFixed(0)}`} color={rsi >= 70 ? '#ef4444' : rsi < 40 ? '#22c55e' : '#60a5fa'} tip={it.setup_advisory} />}
                      <Pill text={it.trend || 'unknown'} color={tcol} />
                      {it.score != null && <Pill text={`score ${Number(it.score).toFixed(0)}`} color={it.watch_score_kind === 'strategy_qualified' ? '#22c55e' : 'var(--text3)'} tip={it.watch_score_kind === 'strategy_qualified' ? 'qualifies for a Bucket-2/3 strategy' : 'technical posture score (not a proposal score)'} />}
                      {a && <Pill text={`${a.advisory_flag === 'caution' ? '⚠ ' : ''}${a.band}`} color={advColor(a.advisory_flag)} tip={a.note} />}
                      {stale && <Pill text="technicals stale" color="#f59e0b" tip="last enriched > 2h ago" />}
                    </div>
                  )}
                  {/* unified info block: what the company does · sector vs sector · analyst · top-3 news */}
                  {(() => {
                    const sc = cardMap[it.symbol]
                    if (!sc) return null
                    return (
                      <div style={{ borderTop: '1px solid var(--border)', paddingTop: 5, display: 'flex', flexDirection: 'column', gap: 3 }}>
                        {sc.description && <div style={{ fontSize: 9.5, color: 'var(--text2)', lineHeight: 1.4 }}>{sc.description}</div>}
                        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
                          {sc.sector && <Pill text={`${sc.sector}${sc.sector_etf ? ` (${sc.sector_etf})` : ''}`} color="#60a5fa" tip={sc.industry || undefined} />}
                          {sc.vs_sector_week != null && <Pill text={`${sc.vs_sector_week >= 0 ? '+' : ''}${sc.vs_sector_week}% vs sector (1w)`}
                            color={sc.vs_sector_week >= 0 ? '#22c55e' : '#ef4444'}
                            tip={`symbol ${sc.perf_week}% vs ${sc.sector_etf} ${sc.sector_perf_week}% (week)`} />}
                          {sc.analyst?.rating && <Pill text={`${String(sc.analyst.rating).replace('_', ' ')} · ${sc.analyst.opinions}an · tgt $${sc.analyst.target}${sc.analyst.upside_pct != null ? ` (${sc.analyst.upside_pct >= 0 ? '+' : ''}${sc.analyst.upside_pct}%)` : ''}`}
                            color={String(sc.analyst.rating).includes('buy') ? '#22c55e' : sc.analyst.rating === 'hold' ? '#f59e0b' : 'var(--text3)'}
                            tip={`analyst consensus ${sc.analyst.mean} · range $${sc.analyst.target_low}–$${sc.analyst.target_high}`} />}
                        </div>
                        {(sc.news ?? []).slice(0, 3).map((n: any, i: number) => (
                          <div key={i} style={{ fontSize: 9, lineHeight: 1.35 }}>
                            <span style={{ color: 'var(--text3)' }}>{n.source} · {n.at ? `${Math.round((Date.now() - new Date(n.at).getTime()) / 36e5)}h` : ''} </span>
                            {n.url ? <a href={n.url} target="_blank" rel="noreferrer" style={{ color: '#93c5fd', textDecoration: 'none' }}>{n.title}</a>
                              : <span style={{ color: 'var(--text2)' }}>{n.title}</span>}
                          </div>
                        ))}
                      </div>
                    )
                  })()}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 9, color: 'var(--text3)' }}>
                    <span>{it.origin_system === 'agent_discovery' ? 'AI-discovered' : originLabel(it.origin_system)}</span>
                    <span style={{ color: '#60a5fa' }}>more intelligence →</span>
                  </div>
                </div>
              )
            })}
          </div>
        )}
        <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 8 }}>Click a card → full provenance + intelligence. Enriched by the standing sweep (rsi/trend/score/advisory). Advisory-only — read-only, never gates.</div>
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
      if (j.ok) {
        // service-at-creation feedback (2026-06-12): ticker directives are evaluated synchronously —
        // tell the operator exactly what happened instead of silently waiting for the cron.
        const sv = j.serviced?.status
        setMsg(`✓ Created directive #${j.directive_id}` +
          (sv === 'PROMOTED' ? ' — symbol PROMOTED to the watchlist now'
            : sv === 'STAGED_FOR_REVIEW' ? ' — staged for your one-tap promote'
            : sv === 'MONITORED_NO_QUALIFY' ? ' — watching now (shown in list; no strategy qualifies yet)'
            : sv ? ` — ${sv}` : ''))
        onCreated(); setTimeout(onClose, sv ? 1600 : 900)
      }
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
