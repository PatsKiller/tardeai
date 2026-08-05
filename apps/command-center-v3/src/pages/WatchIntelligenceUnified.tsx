/**
 * Primary Watch Intelligence workspace.
 * Consumes ONLY the Data Broker projection — no page-side record selection.
 * Zero provider calls on load.
 */
import { useCallback, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { BB, TYPE } from '../lib/watchTokens'

type Card = {
  symbol: string
  company?: string
  company_summary?: string | null
  sector?: string
  industry?: string
  instrument_type?: string
  street_rating?: string
  street_tone?: string
  analyst_count?: number | null
  target_mean?: number | null
  implied_upside_pct?: number | null
  trade_ai_state?: string
  proposal_allowed?: boolean
  last?: number | null
  day_change_pct?: number | null
  price_as_of?: string | null
  price_source?: string | null
  freshness_state?: string | null
  market_session?: string | null
  quote_id?: string | number | null
  source_record_id?: string | null
  support?: number | string | null
  resistance?: number | string | null
  technical_setup?: string | null
  catalyst_summary?: string | null
  catalyst_vs_industry?: string | null
  relative_performance_summary?: string | null
  one_line_thesis?: string | null
  operator_meaning?: string | null
  primary_risk?: string | null
  next_operator_action?: string | null
  next_review_time?: string | null
  held?: boolean
  starred?: boolean
  screener_origin?: boolean
  cio_review?: ReviewStatus
  maria_review?: ReviewStatus
}

type ReviewStatus = {
  status?: string
  summary?: string | null
  provider?: string | null
  model?: string | null
  policy?: string | null
  reason_code?: string | null
  display?: Record<string, string | null | undefined>
  estimated_cost_usd?: number
}

const VIEWS: { id: string; label: string }[] = [
  { id: 'top_ideas', label: 'Top Ideas' },
  { id: 'starred', label: 'Starred' },
  { id: 'held', label: 'Held' },
  { id: 'screener_finds', label: 'Screener Finds' },
  { id: 'near_trigger', label: 'Near Trigger' },
  { id: 'reviewed_today', label: 'Reviewed Today' },
  { id: 'needs_review', label: 'Needs Review' },
  { id: 'needs_data', label: 'Needs Data' },
  { id: 'avoid', label: 'Avoid' },
  { id: 'all', label: 'All' },
]

function money(n?: number | null) {
  if (n == null || !Number.isFinite(Number(n))) return '—'
  return `$${Number(n).toFixed(2)}`
}
function pct(n?: number | null) {
  if (n == null || !Number.isFinite(Number(n))) return '—'
  const v = Number(n)
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}
function stateColor(s?: string) {
  if (!s) return BB.text3
  if (s === 'READY') return BB.green
  if (s === 'WAIT' || s === 'REVIEW_PENDING') return BB.amber
  if (s === 'MANAGING') return BB.text2
  if (s === 'STALE' || s === 'DATA_UNAVAILABLE') return BB.text3
  return BB.red
}

function ReviewBox({ title, rev }: { title: string; rev?: ReviewStatus }) {
  const complete = rev?.status === 'COMPLETE'
  return (
    <div
      style={{ background: BB.bgShift, border: `1px solid ${BB.border}`, borderRadius: 8, padding: 8 }}
      data-review-box
      data-review-status={rev?.status || 'NOT_RUN'}
      data-review-model={complete ? String(rev?.model || '') : 'NONE'}
    >
      <div style={{ fontSize: TYPE.xs, color: BB.text3, fontWeight: 900, letterSpacing: 0.5, textTransform: 'uppercase' }}>{title}</div>
      {complete ? (
        <>
          <div style={{ fontSize: TYPE.sm, color: BB.text1, marginTop: 3, lineHeight: 1.35 }}>{rev?.summary || '—'}</div>
          <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 4 }}>
            {rev?.provider} · {rev?.model} · {rev?.policy}
            {rev?.estimated_cost_usd != null ? ` · $${Number(rev.estimated_cost_usd).toFixed(5)}` : ''}
          </div>
        </>
      ) : (
        <>
          <div style={{ fontSize: TYPE.sm, color: BB.amber, marginTop: 3, fontWeight: 800 }}>
            {rev?.display?.label || `${title}: NOT RUN`}
          </div>
          <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 3 }}>
            Provider NONE · Model NONE · Policy NO_CALL · Cost $0
            {rev?.reason_code ? ` · ${rev.reason_code}` : ''}
          </div>
        </>
      )}
    </div>
  )
}

function qsGet(sp: URLSearchParams, k: string, d = '') {
  return sp.get(k) ?? d
}

export default function WatchIntelligenceUnified() {
  const [sp, setSp] = useSearchParams()
  const view = qsGet(sp, 'view', 'top_ideas')
  const q = qsGet(sp, 'q', '')
  const street = qsGet(sp, 'street_rating', '')
  const state = qsGet(sp, 'trade_ai_state', '')
  const sector = qsGet(sp, 'sector', '')
  const sort = qsGet(sp, 'sort', 'watch_rank')
  const page = qsGet(sp, 'page', '1')
  const layout = qsGet(sp, 'layout', 'grid')
  const starredOnly = qsGet(sp, 'starred', '') === '1'
  const heldOnly = qsGet(sp, 'held', '') === '1'
  const origin = qsGet(sp, 'origin', '')

  const setParam = useCallback((key: string, value: string) => {
    const next = new URLSearchParams(sp)
    if (!value) next.delete(key)
    else next.set(key, value)
    if (key !== 'page') next.set('page', '1')
    setSp(next, { replace: true })
  }, [sp, setSp])

  const apiQs = useMemo(() => {
    const p = new URLSearchParams()
    p.set('view', view || 'top_ideas')
    p.set('page', page || '1')
    p.set('page_size', '40')
    p.set('sort', sort || 'watch_rank')
    if (q) p.set('q', q)
    if (street) p.set('street_rating', street)
    if (state) p.set('trade_ai_state', state)
    if (sector) p.set('sector', sector)
    if (starredOnly) p.set('starred', '1')
    if (heldOnly) p.set('held', '1')
    if (origin) p.set('origin', origin)
    return p.toString()
  }, [view, page, sort, q, street, state, sector, starredOnly, heldOnly, origin])

  const { data, loading, error } = useApi<any>(`/api/v3/data-broker/watch-intelligence?${apiQs}`, 90_000)
  const { data: filters } = useApi<any>('/api/v3/data-broker/watch-filters', 300_000)
  const body = data?.data && data.data.items ? data.data : data
  const cards: Card[] = body?.cards || (body?.items || []).map((i: any) => i.card).filter(Boolean)
  const summary = body?.summary || {}
  const counts = body?.counts || {}
  const filterBody = filters?.data && filters.data.views ? filters.data : filters

  const [selected, setSelected] = useState<string | null>(null)
  const sel = cards.find(c => c.symbol === selected) || cards[0]

  const star = async (symbol: string, action: 'star' | 'unstar') => {
    await fetch('/api/v3/watch/commands/star', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ symbol, action }),
    })
    // force reload via param nudge
    setParam('page', page)
  }

  const activeChips: string[] = []
  if (view && view !== 'top_ideas') activeChips.push(`view:${view}`)
  if (street) activeChips.push(`street:${street}`)
  if (state) activeChips.push(`state:${state}`)
  if (sector) activeChips.push(`sector:${sector}`)
  if (starredOnly) activeChips.push('starred')
  if (heldOnly) activeChips.push('held')
  if (origin) activeChips.push(`origin:${origin}`)
  if (q) activeChips.push(`q:${q}`)

  return (
    <div data-watch-intelligence-primary data-provider-calls={String(body?.provider_calls ?? 0)} data-broker-snapshot={body?.snapshot_id || ''}>
      {/* 1. System truth strip */}
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: TYPE.xs, fontWeight: 900, color: BB.text2, letterSpacing: 1.1, textTransform: 'uppercase' }}>
            Primary Watch workspace
          </div>
          <div style={{ fontSize: TYPE.lg, fontWeight: 900, color: BB.text0, marginTop: 4 }}>WATCH INTELLIGENCE</div>
          <div style={{ fontSize: TYPE.base, color: BB.text3, marginTop: 4 }}>
            Street rating primary · Trade AI independent · broker projection only · page load = 0 provider calls
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <Chip good>Broker {body?.data_contract_version || body?.contract_version || '—'}</Chip>
          <Chip good>Provider calls {body?.provider_calls ?? 0}</Chip>
          <Chip>Paid OFF</Chip>
          <Chip>Broker writes NONE</Chip>
          <Link to="/watch/discovery" style={{ fontSize: TYPE.xs, color: BB.text3, alignSelf: 'center' }}>Discovery →</Link>
        </div>
      </div>

      {/* 2. Counts */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,minmax(0,1fr))', gap: 8, marginBottom: 10 }}>
        <Sum n={summary.street_strong_buy} label="Strong Buy" color={BB.green} />
        <Sum n={summary.street_buy} label="Buy" color={BB.text0} />
        <Sum n={summary.trade_ai_wait} label="Wait" color={BB.amber} />
        <Sum n={summary.blocked_or_unavailable} label="Blocked / fail" color={BB.red} />
        <Sum n={counts.starred_universe ?? filterBody?.counts?.starred} label="Starred" color={BB.text2} />
        <Sum n={counts.held_universe ?? filterBody?.counts?.held} label="Held" color={BB.text2} />
      </div>

      {/* 3. Views */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        {VIEWS.map(v => (
          <button
            key={v.id}
            type="button"
            onClick={() => setParam('view', v.id)}
            style={pill(view === v.id)}
            data-view={v.id}
          >
            {v.label}
          </button>
        ))}
      </div>

      {/* 4. Filter toolbar (Screener controls) */}
      <div
        style={{
          display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center',
          background: BB.bgPanel, border: `1px solid ${BB.border}`, borderRadius: 12, padding: 10, marginBottom: 8,
        }}
        data-filter-toolbar
      >
        <input
          value={q}
          onChange={e => setParam('q', e.target.value)}
          placeholder="Search symbol, company, sector"
          style={inputStyle}
        />
        <select value={street} onChange={e => setParam('street_rating', e.target.value)} style={inputStyle}>
          <option value="">Street rating</option>
          {(filterBody?.street_ratings || ['STRONG BUY', 'BUY', 'HOLD', 'SELL', 'NOT RATED']).map((r: string) => (
            <option key={r} value={r.replace(/ /g, '_')}>{r}</option>
          ))}
        </select>
        <select value={state} onChange={e => setParam('trade_ai_state', e.target.value)} style={inputStyle}>
          <option value="">Trade AI state</option>
          {(filterBody?.trade_ai_states || []).map((r: string) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
        <select value={sector} onChange={e => setParam('sector', e.target.value)} style={inputStyle}>
          <option value="">Sector</option>
          {(filterBody?.sectors || []).map((r: string) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
        <select value={sort} onChange={e => setParam('sort', e.target.value)} style={inputStyle}>
          <option value="watch_rank">Sort: watch rank</option>
          <option value="street_rating">Sort: street</option>
          <option value="day_change">Sort: day change</option>
          <option value="upside">Sort: upside</option>
          <option value="symbol">Sort: symbol</option>
        </select>
        <select value={origin} onChange={e => setParam('origin', e.target.value)} style={inputStyle}>
          <option value="">Origin</option>
          <option value="screener_find">Screener find</option>
        </select>
        <button type="button" style={pill(starredOnly)} onClick={() => setParam('starred', starredOnly ? '' : '1')}>★ Starred only</button>
        <button type="button" style={pill(heldOnly)} onClick={() => setParam('held', heldOnly ? '' : '1')}>Held only</button>
        <button type="button" style={pill(layout === 'grid')} onClick={() => setParam('layout', 'grid')}>Grid</button>
        <button type="button" style={pill(layout === 'table')} onClick={() => setParam('layout', 'table')}>Table</button>
      </div>

      {/* 5. Active chips */}
      {activeChips.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
          {activeChips.map(c => (
            <span key={c} style={{ fontSize: TYPE.xs, border: `1px solid ${BB.border}`, borderRadius: 999, padding: '3px 8px', color: BB.text2 }}>{c}</span>
          ))}
          <button type="button" style={{ ...pill(false), color: BB.amber }} onClick={() => setSp(new URLSearchParams({ view: 'top_ideas' }), { replace: true })}>
            Clear filters
          </button>
        </div>
      )}

      {loading && <div style={{ color: BB.text3, fontSize: TYPE.sm }}>Loading broker projection…</div>}
      {error && <div style={{ color: BB.red, fontSize: TYPE.sm }}>Error: {String(error)}</div>}

      {/* 6. Cards + inspector */}
      <div style={{ display: 'grid', gridTemplateColumns: layout === 'table' ? '1fr' : 'minmax(0,1.5fr) minmax(300px,.85fr)', gap: 12, alignItems: 'start' }}>
        {layout === 'table' ? (
          <table style={{ width: '100%', borderCollapse: 'collapse', background: BB.bgPanel, border: `1px solid ${BB.border}`, borderRadius: 12 }}>
            <thead>
              <tr>
                {['Symbol', 'Street', 'Trade AI', 'Last', 'CIO', 'Maria', 'Action'].map(h => (
                  <th key={h} style={{ textAlign: 'left', fontSize: TYPE.xs, color: BB.text3, padding: 8, borderBottom: `1px solid ${BB.border}` }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cards.map(c => (
                <tr key={c.symbol} onClick={() => setSelected(c.symbol)} style={{ cursor: 'pointer' }} data-intelligence-card data-symbol={c.symbol}>
                  <td style={td}>{c.symbol}{c.starred ? ' ★' : ''}{c.held ? ' H' : ''}</td>
                  <td style={td} data-primary-rating>{c.street_rating}</td>
                  <td style={{ ...td, color: stateColor(c.trade_ai_state) }}>{c.trade_ai_state}</td>
                  <td style={td}>{money(c.last)} {pct(c.day_change_pct)}</td>
                  <td style={td}>{c.cio_review?.status}</td>
                  <td style={td}>{c.maria_review?.status}</td>
                  <td style={td}><Link to={`/watch/intelligence/${c.symbol}`} style={{ color: BB.text2, fontSize: TYPE.xs }}>Open</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,minmax(0,1fr))', gap: 10 }}>
            {cards.map(c => {
              const active = sel?.symbol === c.symbol
              return (
                <div
                  key={c.symbol}
                  role="button"
                  tabIndex={0}
                  onClick={() => setSelected(c.symbol)}
                  data-intelligence-card
                  data-symbol={c.symbol}
                  data-street-rating={c.street_rating}
                  data-trade-ai-state={c.trade_ai_state}
                  data-starred={String(!!c.starred)}
                  data-held={String(!!c.held)}
                  data-screener-origin={String(!!c.screener_origin)}
                  data-cio-status={c.cio_review?.status || 'NOT_RUN'}
                  data-maria-status={c.maria_review?.status || 'NOT_RUN'}
                  style={{
                    background: BB.bgPanel,
                    border: `1px solid ${active ? BB.text2 : BB.border}`,
                    borderRadius: 12,
                    padding: 12,
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                    <div>
                      <div style={{ fontSize: TYPE.lg, fontWeight: 900 }}>
                        {c.symbol}
                        {c.starred ? <span style={{ color: BB.amber, marginLeft: 6 }}>★</span> : null}
                        {c.held ? <span style={{ color: BB.green, marginLeft: 6, fontSize: TYPE.xs }}>HELD</span> : null}
                      </div>
                      <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>{c.company}{c.industry ? ` · ${c.industry}` : ''}</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontWeight: 900 }}>{money(c.last)}</div>
                      <div style={{ fontSize: TYPE.xs, color: Number(c.day_change_pct) >= 0 ? BB.green : BB.red }}>{pct(c.day_change_pct)}</div>
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
                    <span data-primary-rating style={{ border: `1px solid ${BB.border}`, borderRadius: 999, padding: '3px 8px', fontSize: TYPE.xs, fontWeight: 950, color: BB.green }}>
                      {c.street_rating || 'NOT RATED'}
                      {c.analyst_count != null ? ` · ${c.analyst_count}` : ''}
                    </span>
                    <span style={{ border: `1px solid ${BB.border}`, borderRadius: 999, padding: '3px 8px', fontSize: TYPE.xs, color: stateColor(c.trade_ai_state) }}>
                      Trade AI: {c.trade_ai_state}
                    </span>
                    <span style={{ border: `1px solid ${BB.border}`, borderRadius: 999, padding: '3px 8px', fontSize: TYPE.xs, color: BB.text3 }}>
                      {c.freshness_state || '—'}
                    </span>
                  </div>
                  {c.company_summary && (
                    <div style={{ fontSize: TYPE.sm, color: BB.text2, marginTop: 8, lineHeight: 1.4 }} data-company-summary>{c.company_summary}</div>
                  )}
                  <div style={{ fontSize: TYPE.sm, color: BB.text1, marginTop: 8 }}>{c.operator_meaning || c.one_line_thesis || '—'}</div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6, marginTop: 8 }}>
                    <Fact k="Support" v={c.support != null ? String(c.support) : '—'} />
                    <Fact k="Resistance" v={c.resistance != null ? String(c.resistance) : '—'} />
                    <Fact k="Tech" v={c.technical_setup || '—'} />
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 8 }}>
                    <ReviewBox title="CIO" rev={c.cio_review} />
                    <ReviewBox title="Maria" rev={c.maria_review} />
                  </div>
                  <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 8 }}>
                    <b style={{ color: BB.text2 }}>Catalyst:</b> {c.catalyst_summary || '—'}
                  </div>
                  <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 3 }}>
                    <b style={{ color: BB.text2 }}>Relative:</b> {c.relative_performance_summary || '—'}
                  </div>
                  {c.primary_risk && <div style={{ fontSize: TYPE.xs, color: BB.red, marginTop: 6 }}>Risk: {c.primary_risk}</div>}
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 10, gap: 8 }}>
                    <Link to={`/watch/intelligence/${c.symbol}`} style={linkBtn} onClick={e => e.stopPropagation()}>OPEN INTELLIGENCE</Link>
                    <button type="button" style={ghostBtn} onClick={e => { e.stopPropagation(); star(c.symbol, c.starred ? 'unstar' : 'star') }}>
                      {c.starred ? 'Unstar' : 'Star'}
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {layout !== 'table' && (
          <aside style={{ background: BB.bgPanel, border: `1px solid ${BB.border}`, borderRadius: 12, position: 'sticky', top: 12 }} data-intelligence-inspector>
            {sel ? (
              <>
                <div style={{ padding: 14, borderBottom: `1px solid ${BB.border}` }}>
                  <div style={{ fontSize: TYPE.xl, fontWeight: 950 }}>{sel.symbol}</div>
                  <div style={{ fontSize: TYPE.xs, color: BB.text3 }}>{sel.company}</div>
                  <div style={{ marginTop: 8, fontSize: TYPE.md, fontWeight: 800 }}>{sel.operator_meaning}</div>
                </div>
                <div style={{ padding: 12 }}>
                  <div style={{ fontSize: TYPE.xs, color: BB.text3, fontWeight: 900, marginBottom: 6 }}>WHAT THE COMPANY DOES</div>
                  <div style={{ fontSize: TYPE.sm, color: BB.text1 }} data-company-summary>{sel.company_summary || '—'}</div>
                </div>
                <div style={{ padding: 12, borderTop: `1px solid ${BB.border}`, display: 'grid', gap: 6 }}>
                  <ReviewBox title="CIO" rev={sel.cio_review} />
                  <ReviewBox title="Maria" rev={sel.maria_review} />
                </div>
                <div style={{ padding: 12 }}>
                  <Link to={`/watch/intelligence/${sel.symbol}`} style={linkBtn}>OPEN FULL SYMBOL INTELLIGENCE</Link>
                </div>
              </>
            ) : (
              <div style={{ padding: 14, color: BB.text3, fontSize: TYPE.sm }}>Select a card</div>
            )}
          </aside>
        )}
      </div>

      {/* Pagination */}
      <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center' }}>
        <button type="button" style={pill(false)} disabled={Number(page) <= 1} onClick={() => setParam('page', String(Math.max(1, Number(page) - 1)))}>Prev</button>
        <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>Page {page} · matched {counts.total_matched ?? cards.length}</span>
        <button type="button" style={pill(false)} onClick={() => setParam('page', String(Number(page) + 1))}>Next</button>
      </div>

      {/* 8. Collapsed discovery */}
      <details style={{ marginTop: 16, border: `1px solid ${BB.border}`, borderRadius: 10, padding: 10, background: BB.bgPanel }}>
        <summary style={{ cursor: 'pointer', fontSize: TYPE.xs, fontWeight: 900, color: BB.text2 }}>
          Discovery & Administration (collapsed — not primary decision path)
        </summary>
        <div style={{ marginTop: 8, fontSize: TYPE.sm, color: BB.text3, lineHeight: 1.5 }}>
          Full discovery, directives, ToS import, shadow batch, and universe tools live on a separate route.
          <div style={{ marginTop: 8 }}>
            <Link to="/watch/discovery" style={{ color: BB.amber, fontWeight: 800 }}>Open Discovery workspace →</Link>
            {' · '}
            <Link to="/watch-legacy" style={{ color: BB.text3 }}>Legacy rollback route (no nav)</Link>
          </div>
        </div>
      </details>
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  background: BB.bg,
  color: BB.text0,
  border: `1px solid ${BB.border}`,
  borderRadius: 8,
  padding: '6px 8px',
  fontSize: TYPE.sm,
}
const td: React.CSSProperties = { padding: 8, borderBottom: `1px solid ${BB.border}`, fontSize: TYPE.xs, color: BB.text1 }
const linkBtn: React.CSSProperties = {
  background: BB.bgShift, border: `1px solid ${BB.border}`, color: BB.text0,
  borderRadius: 8, padding: '6px 9px', fontSize: TYPE.xs, fontWeight: 900, textDecoration: 'none', display: 'inline-block',
}
const ghostBtn: React.CSSProperties = {
  background: 'transparent', border: `1px solid ${BB.border}`, color: BB.text3,
  borderRadius: 8, padding: '6px 9px', fontSize: TYPE.xs, fontWeight: 800, cursor: 'pointer',
}

function pill(active: boolean): React.CSSProperties {
  return {
    border: `1px solid ${active ? BB.text2 : BB.border}`,
    background: active ? BB.bgShift : BB.bg,
    color: active ? BB.text0 : BB.text3,
    borderRadius: 8,
    padding: '6px 9px',
    fontSize: TYPE.xs,
    fontWeight: 900,
    cursor: 'pointer',
  }
}
function Chip({ children, good }: { children: React.ReactNode; good?: boolean }) {
  return (
    <span style={{ border: `1px solid ${BB.border}`, background: BB.bgPanel, borderRadius: 999, padding: '5px 9px', fontSize: TYPE.xs, color: good ? BB.green : BB.text3 }}>
      {children}
    </span>
  )
}
function Sum({ n, label, color }: { n?: number; label: string; color: string }) {
  return (
    <div style={{ background: BB.bgPanel, border: `1px solid ${BB.border}`, borderRadius: 12, padding: 10 }}>
      <div style={{ fontSize: TYPE.lg, fontWeight: 950, color }}>{n ?? 0}</div>
      <div style={{ fontSize: TYPE.xs, color: BB.text3, textTransform: 'uppercase', marginTop: 2, fontWeight: 800 }}>{label}</div>
    </div>
  )
}
function Fact({ k, v }: { k: string; v: string }) {
  return (
    <div style={{ background: BB.bgShift, border: `1px solid ${BB.border}`, borderRadius: 8, padding: 7 }}>
      <div style={{ fontSize: TYPE.xs, color: BB.text3, textTransform: 'uppercase', fontWeight: 850 }}>{k}</div>
      <div style={{ fontSize: TYPE.xs, color: BB.text1, marginTop: 3 }}>{v}</div>
    </div>
  )
}
