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

// v4 (C1): directive detail drawer — thesis, aliases, 90d hit timeline, α events, children
function DirectiveDrawer({ id, onClose }: { id: number; onClose: () => void }) {
  const { data: det } = useApi<any>(`/api/v2/watch/directives/detail?id=${id}`, 0)
  const d = det?.directive
  const spark = (tl: any[]) => {
    if (!tl?.length) return '—'
    const max = Math.max(...tl.map((t: any) => t.hits))
    const G = '▁▂▃▄▅▆▇█'
    return tl.slice(-30).map((t: any) => G[Math.min(7, Math.round((t.hits / max) * 7))]).join('')
  }
  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.55)', zIndex: 80, display: 'flex', justifyContent: 'flex-end' }}>
      <div onClick={e => e.stopPropagation()} style={{ width: 480, maxWidth: '94vw', height: '100%', overflowY: 'auto', background: BB.bgPanel, borderLeft: `1px solid ${BB.border}`, padding: 14 }}>
        {!d ? <div style={{ color: BB.text3, fontSize: TYPE.sm }}>Loading…</div> : (
          <>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: TYPE.md, fontWeight: 800, color: BB.text0 }}>#{d.id} {d.label}</span>
              <Chip kind="state" tone={d.status === 'active' ? 'green' : d.status === 'paused' || d.status === 'expired' ? 'amber' : 'slate'}>{d.status}</Chip>
              {det.expires_in_days != null && <Chip kind="state" tone={det.expires_in_days <= 7 ? 'amber' : 'slate'}>{det.expires_in_days >= 0 ? `EXPIRES ${det.expires_in_days}d` : 'PAST TTL'}</Chip>}
              <button onClick={onClose} style={{ marginLeft: 'auto', ...terminalButton('ghost') }}>✕</button>
            </div>
            <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 4 }}>{d.kind} · by {d.created_by || 'operator'} · created {String(d.created_at || '').slice(0, 10)} · TA {d.trade_ai_enabled ? '✓' : '✗'} · Hermes {d.hermes_enabled ? '✓' : '✗'}</div>
            {d.rationale && <div style={{ fontSize: TYPE.sm, color: BB.text1, marginTop: 8, lineHeight: 1.5 }}>{d.rationale}</div>}
            {(det.aliases?.length ?? 0) > 0 && (
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: TYPE.xs, fontWeight: 800, color: BB.text3, letterSpacing: '.05em' }}>ALIASES ({det.aliases.length})</div>
                <div style={{ fontSize: TYPE.xs, color: BB.text2, marginTop: 3 }}>{det.aliases.map((a: any) => typeof a === 'string' ? a : a?.label).filter(Boolean).join(' · ')}</div>
              </div>
            )}
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: TYPE.xs, fontWeight: 800, color: BB.text3, letterSpacing: '.05em' }}>HIT TIMELINE (90d)</div>
              <div style={{ ...numStyle, fontSize: TYPE.base, color: T.extIntel.hermes, marginTop: 3 }}>{spark(det.hit_timeline_90d)}</div>
            </div>
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: TYPE.xs, fontWeight: 800, color: BB.text3, letterSpacing: '.05em' }}>OUTCOME LEDGER · α events (n={det.alpha_n} scored of {det.alpha_events?.length ?? 0})</div>
              {(det.alpha_events ?? []).slice(0, 14).map((e: any, i: number) => (
                <div key={i} style={{ display: 'flex', gap: 8, fontSize: TYPE.xs, padding: '2px 4px', borderBottom: `1px solid ${BB.borderHair}`, alignItems: 'baseline' }}>
                  <span style={{ ...numStyle, fontWeight: 700, minWidth: 48, color: BB.text0 }}>{e.symbol}</span>
                  <span style={{ color: BB.text3, minWidth: 72 }}>{e.emitted_on}</span>
                  <span style={{ ...numStyle, color: e.alpha_21d == null ? BB.text3 : e.alpha_21d > 0 ? BB.green : BB.red }}>{e.alpha_21d != null ? `21d α ${e.alpha_21d > 0 ? '+' : ''}${e.alpha_21d}%` : (e.verdict || 'pending')}</span>
                  {e.staged && <Chip kind="state" tone="amber">STAGED</Chip>}
                  {e.proposed && <span style={{ color: T.link }}>→ proposal</span>}
                </div>
              ))}
              {(det.alpha_events?.length ?? 0) === 0 && <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>no candidate events yet</div>}
            </div>
            <div style={{ marginTop: 10 }}>
              <div style={{ fontSize: TYPE.xs, fontWeight: 800, color: BB.text3, letterSpacing: '.05em' }}>WATCHPOOL CHILDREN ({det.children?.length ?? 0})</div>
              {(det.children ?? []).slice(0, 12).map((c: any, i: number) => (
                <div key={i} style={{ display: 'flex', gap: 8, fontSize: TYPE.xs, padding: '2px 4px', alignItems: 'baseline' }}>
                  <span style={{ ...numStyle, fontWeight: 700, minWidth: 48, color: BB.text0 }}>{c.symbol}</span>
                  <span style={{ color: BB.text2, minWidth: 130 }}>{c.strategy_id}</span>
                  <span style={{ color: BB.text3 }}>{String(c.current_status || '').toLowerCase()}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default function WatchpoolHub({ onDrill, embedded }: Props) {
  const [terminalUi] = useTerminalUi()
  const card = hubPanel(terminalUi)
  const { data: wd, refetch: refetchWd } = useApi<any>('/api/v2/watch-directives', 60_000)
  const { data: tw, refetch: refetchTw } = useApi<any>('/api/v2/watch/two-way-curation', 60_000)
  const { data: wp, refetch: refetchWp } = useApi<any>('/api/v2/watchpool', 60_000)
  const { data: mergePlan, refetch: refetchPlan } = useApi<any>('/api/v2/watch/directives/merge-plan', 0)
  const { data: finds } = useApi<any>('/api/v2/screener-finds/candidates', 300_000)
  const [drawerId, setDrawerId] = useState<number | null>(null)
  const [kind, setKind] = useState<'ticker' | 'sector' | 'trend'>('ticker')
  const [label, setLabel] = useState('')
  const [field1, setField1] = useState('')
  const [seeds, setSeeds] = useState('')
  const [rationale, setRationale] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [deskFilter, setDeskFilter] = useState<'all' | 'cio' | 'advisory' | 'defense'>('all')
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

  const promote = async (symbol: string, directive_id: number, source_system?: string) => {
    setBusy(true); setMsg(null)
    try {
      const r = await fetch('/api/v2/watch/directives/promote', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol,
          directive_id,
          reason: `operator one-tap promote${source_system ? ` (${source_system})` : ''}`,
          source_system: source_system || 'operator',
        }),
      })
      const j = await r.json()
      const st = j.result?.status || j.data?.result?.status
      const qs = j.result?.qualified_strategies || j.data?.result?.qualified_strategies
      const ok = j.ok ?? j.data?.ok
      setMsg(ok
        ? `${symbol}: ${st}${qs?.length ? ' → ' + qs.join(', ') : ''}`
        : `Error: ${j.error || j.data?.error || 'promote failed'}`)
      refetchWd(); refetchWp(); refetchTw()
    } catch (e: any) { setMsg('Error: ' + e.message) }
    setBusy(false)
  }

  const directives = wd?.directives ?? []
  const hits = wd?.recent_hits ?? []
  // Desk two-way suggestions: prefer dedicated API field, fall back to two-way-curation
  const deskSuggestionsRaw: any[] =
    (wd?.desk_suggestions?.length ? wd.desk_suggestions : null)
    || (tw?.suggestions?.length ? tw.suggestions : null)
    || (tw?.data?.suggestions?.length ? tw.data.suggestions : null)
    || hits.filter((h: any) =>
      ['cio', 'advisory', 'defense'].includes(String(h.surfaced_by || '').toLowerCase())
      && h.promotion_status === 'STAGED_FOR_REVIEW')
  const deskSuggestions = deskFilter === 'all'
    ? deskSuggestionsRaw
    : deskSuggestionsRaw.filter((h: any) => String(h.surfaced_by || '').toLowerCase() === deskFilter)
  const twHealth = tw?.loop_status || tw?.data?.loop_status
  const twForward = tw?.forward || tw?.data?.forward
  const twReverse = tw?.reverse || tw?.data?.reverse
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

      {/* Two-way desk suggestions inbox — CIO / Advisory / Defense staged candidates */}
      <div style={{ ...card, borderLeft: `3px solid ${T.extIntel.hermes}` }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
          <span style={{ fontSize: TYPE.base, fontWeight: 800, color: BB.text0 }}>Desk suggestions</span>
          <Chip kind="metric" title="Two-way watchlist curation — desks stage suggestions; operator promotes">
            {deskSuggestionsRaw.length} staged
          </Chip>
          {twHealth && (
            <Chip kind="state" tone={twHealth === 'CIRCULATING' ? 'green' : twHealth === 'COLD' ? 'slate' : 'amber'}
              title="two-way loop health">{twHealth}</Chip>
          )}
          {twReverse && (
            <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>
              reverse · outcome {twReverse.with_realized_outcome ?? 0} · research {twReverse.with_hermes_research ?? 0}
              {(twForward?.desk_hits_24h && Object.keys(twForward.desk_hits_24h).length > 0)
                ? ` · 24h desk hits ${Object.entries(twForward.desk_hits_24h).map(([k, v]) => `${k}:${v}`).join(' ')}`
                : ''}
            </span>
          )}
          <span style={{ flex: 1 }} />
          {(['all', 'cio', 'advisory', 'defense'] as const).map(f => (
            <button key={f} onClick={() => setDeskFilter(f)}
              style={{
                fontSize: TYPE.xs, fontWeight: deskFilter === f ? 800 : 500, padding: '2px 8px', borderRadius: 2, cursor: 'pointer',
                textTransform: 'uppercase', letterSpacing: 0.3,
                background: deskFilter === f ? BB.amberDim : BB.bgShift,
                color: deskFilter === f ? BB.amber : BB.text2,
                border: `1px solid ${deskFilter === f ? BB.amber : BB.border}`,
              }}>{f}</button>
          ))}
        </div>
        {deskSuggestions.length === 0 ? (
          <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>
            No desk-staged candidates right now. CIO reactive / advisory opinions / defense recs emit into staging; the app drain surfaces them here for one-tap promote.
          </div>
        ) : (
          <div>
            {deskSuggestions.map((h: any, i: number) => (
              <div key={`${h.hit_id || h.symbol}-${i}`}
                style={{
                  display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
                  padding: '6px 4px', borderBottom: `1px solid ${BB.borderHair}`,
                  borderLeft: `3px solid ${RAIL.attention}`,
                }}>
                <b style={{ ...numStyle, minWidth: 52, color: BB.text0, cursor: 'pointer' }}
                  onClick={() => onDrill({
                    title: `${h.symbol} — desk suggestion`,
                    subtitle: `${h.surfaced_by} · ${h.label || h.directive_label || ''}`,
                    endpoint: `/api/v2/watch/provenance/${h.symbol}`,
                    rows: [h],
                  })}>{h.symbol}</b>
                <Chip kind="metric">{h.surfaced_by}</Chip>
                <span style={{ fontSize: TYPE.xs, color: BB.text2, flex: '1 1 160px' }}>
                  {h.label || h.directive_label || `directive #${h.directive_id}`}
                </span>
                {h.divergence && <Chip kind="state" tone={divTone(h.divergence)}>{h.divergence}</Chip>}
                <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>
                  {String(h.surfaced_at || '').slice(0, 16).replace('T', ' ')}
                </span>
                <button
                  disabled={busy || !h.directive_id}
                  onClick={() => promote(h.symbol, h.directive_id, h.surfaced_by)}
                  style={{ ...terminalButton('primary'), marginLeft: 'auto', opacity: busy ? 0.5 : 1, cursor: busy ? 'wait' : 'pointer' }}
                  title="Operator one-tap promote — still advisory; scalp firewall applies"
                >Promote</button>
              </div>
            ))}
          </div>
        )}
        <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 8 }}>
          Two-way curation · READ_ONLY_ADVISORY · Promote uses the governor path (no orders). Source: CIO / Advisory / Defense desks.
        </div>
      </div>

      {/* v4 (C3): tier-3 family-merge approvals — same governed merge_into as the Telegram/CLI path */}
      {(mergePlan?.merges?.length ?? 0) > 0 && (
        <div style={{ ...card, borderLeft: `3px solid ${RAIL.attention}` }}>
          <div style={{ fontSize: TYPE.base, fontWeight: 800, color: BB.amber, marginBottom: 6 }}>
            Tier-3 merge approvals ({mergePlan.count}) — Sunday hygiene plan, operator decision
          </div>
          {mergePlan.merges.map((m: any, i: number) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', padding: '5px 0', borderBottom: `1px solid ${BB.borderHair}`, fontSize: TYPE.sm }}>
              <Chip kind="metric">{m.family}</Chip>
              <span style={{ color: BB.text2 }}>
                {m.dups.map((x: any) => `#${x.id} ${x.label} (${x.hits ?? 0} hits)`).join(' + ')} → <b style={{ color: BB.text0 }}>#{m.survivor.id} {m.survivor.label}</b> ({m.survivor.hits ?? 0} hits)
              </span>
              <button disabled={busy} style={{ ...terminalButton('primary'), marginLeft: 'auto' }}
                onClick={async () => {
                  setBusy(true); setMsg(null)
                  try {
                    for (const dup of m.dups) {
                      const r = await fetch('/api/v2/watch/directives/update', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: dup.id, action: 'merge_into', target_id: m.survivor.id }) })
                      const j = await r.json()
                      const jj = j?.data ?? j
                      if (!(jj?.ok)) { setMsg(`Error merging #${dup.id}: ${jj?.error || 'failed'}`); setBusy(false); return }
                    }
                    setMsg(`✓ Merged ${m.dups.length} directive(s) into #${m.survivor.id} — aliases attached, hits reassigned`)
                    refetchWd(); refetchPlan()
                  } catch (e: any) { setMsg('Error: ' + e.message) }
                  setBusy(false)
                }}>Approve merge</button>
            </div>
          ))}
          <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 6 }}>{mergePlan.note}</div>
        </div>
      )}

      {/* Directives + hits + Promote */}
      <div style={card}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 8 }}>
          <span style={{ fontSize: TYPE.base, fontWeight: 800, color: BB.text0 }}>Directives</span>
          {/* v4 (C4): evidence next to the cap — data display only, operator decides tuning */}
          {(() => {
            const ps = (finds?.track_record?.per_source ?? []).find((s: any) => s.source_type === 'directive_hit')
            return ps ? (
              <Chip kind="metric" title="directive-origin candidate outcomes from the source scoreboard (21d α median vs SPY) — evidence for cap tuning; nothing auto-tunes">
                sweep cap 180 · pool 21d α {ps.alpha_21d_median != null ? `${ps.alpha_21d_median > 0 ? '+' : ''}${ps.alpha_21d_median}%` : 'n/a'} (n={ps.n})
              </Chip>
            ) : null
          })()}
          <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>click a row for the full drawer</span>
        </div>
        {directives.length === 0 ? <div style={{ fontSize: TYPE.sm, color: BB.text3 }}>No directives yet — add one above.</div> :
          directives.map((d: any) => {
            const dhits = hits.filter((h: any) => h.directive_id === d.id)
            const rail = d.status === 'paused' ? RAIL.attention : d.status === 'active' ? RAIL.favorable : RAIL.neutral
            return (
              <div key={d.id} onClick={() => setDrawerId(d.id)}
                   style={{ padding: '8px 6px', borderBottom: `1px solid ${BB.border}`, borderLeft: `3px solid ${rail}`, cursor: 'pointer' }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <Chip kind="metric">{d.kind}</Chip>
                  <span style={{ fontWeight: 700, color: BB.text0, fontSize: TYPE.base }}>{d.label}</span>
                  <Chip kind="state" tone={d.status === 'active' ? 'green' : d.status === 'paused' || d.status === 'expired' ? 'amber' : 'slate'}
                        title={d.status === 'paused' ? 'Auto-paused (cold) — advisory; operator un-pause' : d.status === 'expired' ? 'TTL reached (Sunday hygiene) — resume to reactivate' : undefined}>{d.status}</Chip>
                  {d.expires_in_days != null && d.status === 'active' && d.expires_in_days <= 14 && (
                    <Chip kind="state" tone="amber" title={`ttl_days=${d.ttl_days} — enforced by Sunday hygiene since v4`}>{d.expires_in_days > 0 ? `EXPIRES ${d.expires_in_days}d` : 'EXPIRES SUN'}</Chip>
                  )}
                  {d.gap_type === 'rotate_gap' && <Chip kind="state" tone="amber" title={`Held position flagged for rotation review — seek ${d.sleeve || 'sleeve'} replacement (advisory). via ${d.created_by || 'operator'}`}>{`ROTATE-GAP${d.sleeve ? ' · ' + d.sleeve : ''}`}</Chip>}
                  <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>TA {d.trade_ai_enabled ? '✓' : '✗'} · Hermes {d.hermes_enabled ? '✓' : '✗'}</span>
                </div>
                {dhits.length > 0 && (
                  <div onClick={e => e.stopPropagation()} style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
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
      {drawerId != null && <DirectiveDrawer id={drawerId} onClose={() => setDrawerId(null)} />}
    </div>
  )
}
