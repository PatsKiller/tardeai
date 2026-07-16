import { useEffect, useRef, useState } from 'react'
import { useApi } from '../hooks/useApi'
import type { DrillContext } from '../components/DetailDrawer'
import { useTerminalUi } from '../lib/terminalUi'
import { hubPanel, BB, T, TYPE, RAIL, numStyle, terminalButton, focusStyle } from '../lib/watchTokens'
import { Chip } from '../components/TerminalChip'

// v3 Watchpool & Directives — operator watch directives (ticker/sector/trend) + the unified
// strategy_watchpool, with the shared provenance pill row. Advisory; Hermes-firewall preserved.
// v4 (WS-A): watchTokens sweep — zero raw hexes, type floor 10, rails, chip vocabulary,
// j/k keyboard on the pool list.

interface Props { onDrill: (ctx: DrillContext) => void; embedded?: boolean }

// Watch Desk v2 (A3): ONE dictionary for raw pipeline states → human labels
const STATUS_LABELS: Record<string, { label: string; tip: string }> = {
  unavailable: { label: 'Data unavailable', tip: 'Not currently tradable — required data feed unavailable' },
  monitored_no_qualify: { label: 'Monitored — not qualified', tip: 'Monitored — has not met qualification criteria yet' },
  'monitored no qualify': { label: 'Monitored — not qualified', tip: 'Monitored — has not met qualification criteria yet' },
}
const humanStatus = (s?: string) => STATUS_LABELS[String(s || '').toLowerCase()] || { label: s || '—', tip: s || '' }

const divTone = (d?: string): 'green' | 'amber' | 'red' | 'slate' =>
  (({ aligned: 'green', mixed: 'amber', divergent: 'red' } as any)[d || ''] || 'slate')

const poolRail = (status?: string): string => {
  const s = String(status || '').toUpperCase()
  if (s === 'ACTIVE' || s === 'PROPOSED' || s === 'QUALIFIED') return RAIL.favorable
  if (s === 'STAGED_FOR_REVIEW' || s.startsWith('MONITORED')) return RAIL.attention
  if (s === 'REJECTED' || s === 'UNAVAILABLE') return RAIL.breach
  return RAIL.neutral
}

function Field({ label, value, onChange, ph, wide }: any) {
  return (
    <label style={{ fontSize: TYPE.xs, color: BB.text3, display: 'flex', flexDirection: 'column', gap: 2 }}>{label}
      <input value={value} onChange={e => onChange(e.target.value)} placeholder={ph}
        style={{ fontSize: TYPE.sm, padding: '5px 8px', background: BB.bgShift, border: `1px solid ${BB.border}`, borderRadius: 2, color: BB.text0, width: wide ? 200 : 128 }} />
    </label>
  )
}

export default function WatchpoolHub({ onDrill, embedded }: Props) {
  const [terminalUi] = useTerminalUi()
  const card = hubPanel(terminalUi)
  const { data: wd, refetch: refetchWd } = useApi<any>('/api/v2/watch-directives', 60_000)
  const { data: wp, refetch: refetchWp } = useApi<any>('/api/v2/watchpool', 60_000)
  const [kind, setKind] = useState<'ticker' | 'sector' | 'trend'>('ticker')
  const [label, setLabel] = useState('')
  const [field1, setField1] = useState('')
  const [seeds, setSeeds] = useState('')
  const [rationale, setRationale] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [fStatus, setFStatus] = useState('all')   // watchpool status filter (clickable top row)
  const [page, setPage] = useState(0)
  const PER_PAGE = 50
  useEffect(() => setPage(0), [fStatus])   // reset to page 1 when the status filter changes

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
  const allRows = wp?.rows ?? []
  const pool = fStatus === 'all' ? allRows : allRows.filter((r: any) => String(r.current_status).toUpperCase() === fStatus.toUpperCase())
  const pageCount = Math.max(1, Math.ceil(pool.length / PER_PAGE))
  const curPage = Math.min(page, pageCount - 1)
  const pagePool = pool.slice(curPage * PER_PAGE, (curPage + 1) * PER_PAGE)

  // A5: j/k row focus + Enter drill on the pool list (list-dense tab)
  const [focusIdx, setFocusIdx] = useState<number>(-1)
  const listRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tgt = e.target as HTMLElement
      if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.tagName === 'SELECT')) return
      if (e.key === 'j') setFocusIdx(i => Math.min(pagePool.length - 1, i + 1))
      else if (e.key === 'k') setFocusIdx(i => Math.max(0, i - 1))
      else if (e.key === 'Enter' && focusIdx >= 0 && pagePool[focusIdx]) {
        const r = pagePool[focusIdx]
        onDrill({ title: `${r.symbol} — provenance`, subtitle: `${r.strategy_id} · ${r.bucket}`, endpoint: `/api/v2/watch/provenance/${r.symbol}`, rows: [r] })
      } else return
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [pagePool, focusIdx, onDrill])

  const pager = pageCount > 1 ? (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={curPage === 0} style={{ ...terminalButton('secondary'), opacity: curPage === 0 ? 0.4 : 1 }}>‹ Prev</button>
      <span style={{ ...numStyle, fontSize: TYPE.xs, color: BB.text2, fontWeight: 700, minWidth: 92, textAlign: 'center' }}>Page {curPage + 1} / {pageCount} · {curPage * PER_PAGE + 1}-{Math.min((curPage + 1) * PER_PAGE, pool.length)}</span>
      <button onClick={() => setPage(p => Math.min(pageCount - 1, p + 1))} disabled={curPage >= pageCount - 1} style={{ ...terminalButton('secondary'), opacity: curPage >= pageCount - 1 ? 0.4 : 1 }}>Next ›</button>
    </div>
  ) : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {!embedded && (
        <div>
          <div style={{ fontSize: TYPE.lg, fontWeight: 800, color: BB.text0 }}>Watchpool &amp; Directives</div>
          <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>{wd?.directive_count ?? 0} directives · {wp?.count ?? 0} watchpool entries · advisory · Hermes-firewall preserved (Hermes proposes via staging only)</div>
        </div>
      )}

      {/* Add directive */}
      <div style={card}>
        <div style={{ fontSize: TYPE.base, fontWeight: 800, color: BB.text0, marginBottom: 8 }}>Add Watch Directive</div>
        <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
          {(['ticker', 'sector', 'trend'] as const).map(k => (
            <button key={k} onClick={() => setKind(k)}
              style={{ ...(kind === k ? terminalButton('primary') : terminalButton('secondary')), textTransform: 'capitalize' }}>{k}</button>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <Field label={kind === 'ticker' ? 'Symbol' : kind === 'sector' ? 'Finviz Sector' : 'Keywords (comma-sep)'} value={field1} onChange={setField1}
            ph={kind === 'ticker' ? 'RKLB' : kind === 'sector' ? 'Technology' : 'AI datacenter, power'} />
          {kind !== 'ticker' && <Field label={kind === 'sector' ? 'Extra universe (opt)' : 'Seed symbols (opt)'} value={seeds} onChange={setSeeds} ph="NVDA, AMD" />}
          <Field label="Label (opt)" value={label} onChange={setLabel} ph="auto" />
          <Field label="Rationale" value={rationale} onChange={setRationale} ph="thesis" wide />
          <button disabled={busy || !field1} onClick={createDirective} style={{ ...terminalButton('primary'), opacity: busy || !field1 ? 0.5 : 1, cursor: busy || !field1 ? 'not-allowed' : 'pointer' }}>Watch</button>
        </div>
        {msg && <div style={{ fontSize: TYPE.xs, color: msg.startsWith('Error') ? BB.red : BB.green, marginTop: 8 }}>{msg}</div>}
        <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 6 }}>Ticker = exact symbol (auto-evaluated). Sector = ETF + Finviz constituents. Trend = keywords (Hermes discovers → stages). Sector/trend hits stage for one-tap.</div>
      </div>

      {/* Directives + hits + Promote */}
      <div style={card}>
        <div style={{ fontSize: TYPE.base, fontWeight: 800, color: BB.text0, marginBottom: 8 }}>Directives</div>
        {directives.length === 0 ? <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>No directives yet — add one above.</div> :
          directives.map((d: any) => {
            const dhits = hits.filter((h: any) => h.directive_id === d.id)
            const rail = d.status === 'paused' ? RAIL.attention : d.status === 'active' ? RAIL.favorable : RAIL.neutral
            return (
              <div key={d.id} style={{ padding: '8px 6px', borderBottom: `1px solid ${BB.border}`, borderLeft: `3px solid ${rail}` }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <Chip kind="metric">{d.kind}</Chip>
                  <span style={{ fontWeight: 700, color: BB.text0, fontSize: TYPE.base }}>{d.label}</span>
                  <Chip kind="state" tone={d.status === 'active' ? 'green' : d.status === 'paused' ? 'amber' : 'slate'}
                        title={d.status === 'paused' ? 'Auto-paused (cold) — advisory; operator un-pause' : undefined}>{d.status}</Chip>
                  {d.gap_type === 'rotate_gap' && <Chip kind="state" tone="amber" title={`Held position flagged for rotation review — seek ${d.sleeve || 'sleeve'} replacement (advisory). via ${d.created_by || 'operator'}`}>{`ROTATE-GAP${d.sleeve ? ' · ' + d.sleeve : ''}`}</Chip>}
                  <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>TA {d.trade_ai_enabled ? '✓' : '✗'} · Hermes {d.hermes_enabled ? '✓' : '✗'}</span>
                </div>
                {dhits.length > 0 && (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                    {dhits.slice(0, 14).map((h: any, i: number) => (
                      <span key={i} style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontSize: TYPE.xs, padding: '2px 6px', borderRadius: 2, background: BB.bgShift }}>
                        <b style={{ ...numStyle, color: BB.text0, cursor: 'pointer' }}
                          onClick={() => onDrill({ title: `${h.symbol} — provenance`, subtitle: d.label, endpoint: `/api/v2/watch/provenance/${h.symbol}`, rows: [h] })}>{h.symbol}</b>
                        <Chip kind="metric">{h.surfaced_by}</Chip>
                        {h.divergence && <Chip kind="state" tone={divTone(h.divergence)} title="internal vs Street">{h.divergence}</Chip>}
                        <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>{(h.promotion_status || '').replace(/_/g, ' ').toLowerCase()}</span>
                        {h.promotion_status === 'STAGED_FOR_REVIEW' && (
                          <button onClick={() => promote(h.symbol, d.id)} disabled={busy}
                            style={{ ...terminalButton('primary'), cursor: busy ? 'wait' : 'pointer' }}>Promote</button>
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
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
          <span style={{ fontSize: TYPE.base, fontWeight: 800, color: BB.text0 }}>Watchpool</span>
          {/* clickable status row — each chip filters the pool; 'all' resets */}
          {([['all', allRows.length]] as any[]).concat(Object.entries(wp?.by_status ?? {})).map(([k, v]: any) => {
            const active = fStatus.toUpperCase() === String(k).toUpperCase()
            return (
              <button key={k} onClick={() => setFStatus(k)} title={`show ${String(k).toLowerCase()}`}
                style={{ fontSize: TYPE.xs, fontWeight: active ? 800 : 600, padding: '3px 9px', borderRadius: 2, cursor: 'pointer',
                  background: active ? BB.amberDim : BB.bgShift, color: active ? BB.amber : BB.text2,
                  border: `1px solid ${active ? BB.amber : BB.border}` }}>
                {v} {String(k).toLowerCase()}
              </button>
            )
          })}
          <span style={{ flex: 1 }} />
          {pager}
        </div>
        {pool.length === 0 ? <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>Watchpool empty.</div> : (<>
          <div style={{ display: 'flex', fontSize: TYPE.xs, color: BB.text3, padding: '0 6px 4px', textTransform: 'uppercase', letterSpacing: 0.3 }}>
            <span style={{ flex: '0 0 64px' }}>Symbol</span><span style={{ flex: '0 0 160px' }}>Strategy</span><span style={{ flex: '0 0 96px' }}>Bucket</span><span style={{ flex: '0 0 110px' }}>Status</span><span style={{ flex: '1 1 auto' }}>Origin</span>
          </div>
          <div ref={listRef}>
          {pagePool.map((r: any, ri: number) => (
            <div key={r.id} onClick={() => onDrill({ title: `${r.symbol} — provenance`, subtitle: `${r.strategy_id} · ${r.bucket}`, endpoint: `/api/v2/watch/provenance/${r.symbol}`, rows: [r] })}
              style={{ display: 'flex', alignItems: 'center', padding: '4px 6px', borderBottom: `1px solid ${BB.borderHair}`,
                       borderLeft: `3px solid ${poolRail(r.current_status)}`, cursor: 'pointer', fontSize: TYPE.sm,
                       ...(ri === focusIdx ? { background: BB.bgShift } : {}), ...focusStyle(ri === focusIdx) }}>
              <span style={{ ...numStyle, flex: '0 0 64px', fontWeight: 700, color: BB.text0 }}>{r.symbol}</span>
              <span style={{ flex: '0 0 160px', color: BB.text2, fontSize: TYPE.xs }}>{r.strategy_id}</span>
              <span style={{ flex: '0 0 96px' }}><Chip kind="metric">{r.bucket || '?'}</Chip></span>
              <span title={humanStatus(r.current_status).tip} style={{ flex: '0 0 110px', color: BB.text2, fontSize: TYPE.xs }}>{humanStatus(r.current_status).label}</span>
              <span style={{ flex: '1 1 auto', display: 'flex', gap: 5, alignItems: 'center' }}>
                <Chip kind="metric">{r.origin_system || 'screener'}</Chip>
                {r.directive_label && <span style={{ fontSize: TYPE.xs, color: T.extIntel.hermes }}>◆ {r.directive_label}</span>}
              </span>
            </div>
          ))}
          </div>
          {pageCount > 1 && <div style={{ display: 'flex', justifyContent: 'center', marginTop: 10 }}>{pager}</div>}
        </>)}
        <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 8 }}>Click a row for full provenance (origin · tier · Street consensus · divergence). Keys: j/k move · Enter opens. Advisory — promotion is gated; no execution.</div>
      </div>
    </div>
  )
}
