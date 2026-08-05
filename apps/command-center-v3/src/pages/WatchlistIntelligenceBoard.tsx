/**
 * Watchlist Intelligence Board (shadow) — Street rating primary;
 * CIO/Maria only COMPLETE with immutable provenance. Zero provider calls on load.
 */
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { BB, TYPE } from '../lib/watchTokens'

type ReviewStatus = {
  status?: string
  summary?: string | null
  provider?: string | null
  model?: string | null
  policy?: string | null
  reason_code?: string | null
  display?: {
    label?: string
    provider?: string
    model?: string
    policy?: string
    cost?: string
    reason?: string | null
  }
  estimated_cost_usd?: number
}

type Card = {
  symbol: string
  company?: string
  company_summary?: string | null
  sector?: string
  industry?: string
  instrument_type?: string
  street_rating?: string
  street_tone?: string
  street_consensus?: {
    analyst_count?: number | null
    target_mean?: number | null
    implied_upside_pct?: number | null
  }
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
  primary_risk?: string | null
  next_operator_action?: string | null
  next_review_time?: string | null
  held?: boolean
  cio_review?: ReviewStatus
  maria_review?: ReviewStatus
  sentinel_review?: ReviewStatus
}

function money(n?: number | null) {
  if (n == null || !Number.isFinite(Number(n))) return '—'
  return `$${Number(n).toFixed(2)}`
}
function pct(n?: number | null) {
  if (n == null || !Number.isFinite(Number(n))) return '—'
  const v = Number(n)
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`
}
function streetClass(tone?: string) {
  if (tone === 'strong') return { color: BB.green, border: BB.green, bg: BB.bgShift }
  if (tone === 'buy') return { color: BB.text0, border: BB.text2, bg: BB.bgShift }
  return { color: BB.amber, border: BB.border, bg: BB.bgShift }
}
function stateColor(s?: string) {
  if (!s) return BB.text3
  if (s === 'READY') return BB.green
  if (s === 'WAIT' || s === 'REVIEW_PENDING') return BB.amber
  if (s === 'MANAGING') return BB.text2
  if (s === 'STALE' || s === 'DATA_UNAVAILABLE') return BB.text3
  return BB.red
}

function ReviewBox({ title, rev, deep }: { title: string; rev?: ReviewStatus; deep?: boolean }) {
  const complete = rev?.status === 'COMPLETE'
  return (
    <div
      style={{
        background: BB.bgShift,
        border: `1px solid ${deep ? BB.border : BB.border}`,
        borderRadius: 8,
        padding: 8,
      }}
      data-review-box
      data-review-agent={title}
      data-review-status={rev?.status || 'NOT_RUN'}
      data-review-model={complete ? String(rev?.model || '') : 'NONE'}
      data-review-provider={complete ? String(rev?.provider || '') : 'NONE'}
    >
      <div style={{ fontSize: TYPE.xs, color: BB.text3, fontWeight: 900, letterSpacing: 0.6, textTransform: 'uppercase' }}>
        {title}
      </div>
      {complete ? (
        <>
          <div style={{ fontSize: TYPE.sm, color: BB.text1, marginTop: 3, lineHeight: 1.35 }}>
            {rev?.summary || '—'}
          </div>
          <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 4 }}>
            {rev?.provider || '—'} · {rev?.model || '—'} · {rev?.policy || '—'}
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

export default function WatchlistIntelligenceBoard() {
  const { data, loading, error } = useApi<any>('/api/v3/watchlist/intelligence?limit=24&priority=1', 120_000)
  const body = data?.data && typeof data.data === 'object' && data.data.cards ? data.data : data
  const cards: Card[] = body?.cards || []
  const summary = body?.summary || {}
  const [filter, setFilter] = useState('ALL')
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState<string | null>(null)

  const filtered = useMemo(() => {
    const qq = q.trim().toUpperCase()
    return cards.filter(c => {
      const okFilter =
        filter === 'ALL' ||
        c.street_rating === filter ||
        c.trade_ai_state === filter ||
        (filter === 'MANAGING' && (c.trade_ai_state === 'MANAGING' || c.held))
      const okQ =
        !qq ||
        `${c.symbol} ${c.company} ${c.sector} ${c.industry}`.toUpperCase().includes(qq)
      return okFilter && okQ
    })
  }, [cards, filter, q])

  const sel = filtered.find(c => c.symbol === selected) || filtered[0]

  const filters = [
    ['ALL', 'TOP IDEAS'],
    ['STRONG BUY', 'STRONG BUY'],
    ['BUY', 'BUY'],
    ['WAIT', 'WAIT'],
    ['BLOCKED', 'BLOCKED'],
    ['MANAGING', 'HELD / MANAGING'],
  ] as const

  return (
    <div data-watchlist-intelligence-board data-provider-calls={String(body?.provider_calls ?? 0)}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: TYPE.xs, fontWeight: 900, color: BB.text2, letterSpacing: 1.2, textTransform: 'uppercase' }}>
            Shadow research surface
          </div>
          <div style={{ fontSize: TYPE.lg, fontWeight: 900, color: BB.text0, marginTop: 4 }}>
            Watchlist Intelligence Board
          </div>
          <div style={{ fontSize: TYPE.base, color: BB.text3, marginTop: 4 }}>
            Street Strong Buy/Buy is the primary card label. Trade AI state remains independent. Page load = 0 provider calls.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <Chip good>Quotes identified</Chip>
          <Chip good>Provider calls {body?.provider_calls ?? 0}</Chip>
          <Chip>Paid synthesis OFF</Chip>
          <Chip>Broker writes NONE</Chip>
        </div>
      </div>

      <div
        style={{
          border: `1px solid ${BB.border}`,
          background: BB.bgShift,
          color: BB.amber,
          padding: '8px 10px',
          borderRadius: 8,
          fontSize: TYPE.xs,
          marginBottom: 12,
        }}
      >
        <b>SHADOW — not production Watch.</b> CIO/Maria show COMPLETE only with immutable provenance.
        Missing reviews show Provider NONE / Model NONE. Existing Watch route remains for rollback.
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, minmax(0,1fr))', gap: 8, marginBottom: 12 }}>
        <Sum n={summary.street_strong_buy} label="Street Strong Buy" color={BB.green} />
        <Sum n={summary.street_buy} label="Street Buy" color={BB.text0} />
        <Sum n={summary.trade_ai_wait} label="Trade AI Wait" color={BB.amber} />
        <Sum n={summary.blocked_or_unavailable} label="Blocked / unavailable" color={BB.red} />
        <Sum n={summary.managing_held} label="Managing held" color={BB.text2} />
        <Sum n={summary.proposal_eligible} label="Proposal eligible" color={BB.text3} />
      </div>

      <div
        style={{
          display: 'flex',
          gap: 8,
          flexWrap: 'wrap',
          alignItems: 'center',
          background: BB.bgPanel,
          border: `1px solid ${BB.border}`,
          borderRadius: 12,
          padding: 10,
          marginBottom: 12,
        }}
      >
        {filters.map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            style={{
              border: `1px solid ${filter === key ? BB.text2 : BB.border}`,
              background: filter === key ? BB.bgShift : BB.bg,
              color: filter === key ? BB.text0 : BB.text3,
              borderRadius: 8,
              padding: '6px 9px',
              fontSize: TYPE.xs,
              fontWeight: 900,
              cursor: 'pointer',
            }}
          >
            {label}
          </button>
        ))}
        <input
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="Search symbol, company, sector"
          style={{
            background: BB.bg,
            color: BB.text0,
            border: `1px solid ${BB.border}`,
            borderRadius: 8,
            padding: '6px 9px',
            minWidth: 200,
            fontSize: TYPE.sm,
          }}
        />
      </div>

      {loading && <div style={{ color: BB.text3, fontSize: TYPE.sm }}>Loading intelligence…</div>}
      {error && <div style={{ color: BB.red, fontSize: TYPE.sm }}>Error: {String(error)}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.5fr) minmax(320px,.85fr)', gap: 12, alignItems: 'start' }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0,1fr))', gap: 10 }}>
          {filtered.map(c => {
            const sc = streetClass(c.street_tone)
            const active = sel?.symbol === c.symbol
            return (
              <div
                key={c.symbol}
                role="button"
                tabIndex={0}
                onClick={() => setSelected(c.symbol)}
                onKeyDown={e => e.key === 'Enter' && setSelected(c.symbol)}
                data-intelligence-card
                data-symbol={c.symbol}
                data-street-rating={c.street_rating}
                data-trade-ai-state={c.trade_ai_state}
                data-quote-id={c.quote_id != null ? String(c.quote_id) : ''}
                data-source-record-id={c.source_record_id || ''}
                data-freshness-state={c.freshness_state || ''}
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
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                  <div>
                    <div style={{ fontSize: TYPE.lg, fontWeight: 900, color: BB.text0 }}>{c.symbol}</div>
                    <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 2 }}>
                      {c.company}
                      {c.industry ? ` · ${c.industry}` : ''}
                      {c.held ? ' · HELD' : ''}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: TYPE.md, fontWeight: 900 }}>{money(c.last)}</div>
                    <div style={{ fontSize: TYPE.xs, fontWeight: 800, color: Number(c.day_change_pct) >= 0 ? BB.green : BB.red }}>
                      {pct(c.day_change_pct)}
                    </div>
                  </div>
                </div>

                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10, alignItems: 'center' }}>
                  <span
                    data-primary-rating
                    style={{
                      border: `1px solid ${sc.border}`,
                      color: sc.color,
                      background: sc.bg,
                      borderRadius: 999,
                      padding: '4px 8px',
                      fontSize: TYPE.xs,
                      fontWeight: 950,
                    }}
                  >
                    {c.street_rating || 'NOT RATED'}
                    {c.street_consensus?.analyst_count != null ? ` · ${c.street_consensus.analyst_count}` : ''}
                  </span>
                  <span style={{ border: `1px solid ${BB.border}`, borderRadius: 999, padding: '3px 7px', fontSize: TYPE.xs, fontWeight: 900, color: stateColor(c.trade_ai_state) }}>
                    Trade AI: {c.trade_ai_state}
                  </span>
                  <span style={{ border: `1px solid ${BB.border}`, borderRadius: 999, padding: '3px 7px', fontSize: TYPE.xs, color: BB.text3 }}>
                    {c.freshness_state || '—'} · {c.price_source || '—'}
                  </span>
                </div>

                {c.company_summary && (
                  <div style={{ fontSize: TYPE.sm, color: BB.text2, marginTop: 8, lineHeight: 1.4 }} data-company-summary>
                    {c.company_summary}
                  </div>
                )}

                <div style={{ fontSize: TYPE.sm, color: BB.text1, marginTop: 8, lineHeight: 1.4 }}>
                  {c.one_line_thesis || '—'}
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6, marginTop: 10 }}>
                  <Fact k="Support" v={c.support != null ? String(c.support) : '—'} />
                  <Fact k="Resistance" v={c.resistance != null ? String(c.resistance) : '—'} />
                  <Fact k="Technical" v={c.technical_setup || '—'} />
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 8 }}>
                  <ReviewBox title="CIO" rev={c.cio_review} />
                  <ReviewBox title="Maria" rev={c.maria_review} deep />
                </div>

                <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 8 }}>
                  <b style={{ color: BB.text2 }}>Catalyst:</b> {c.catalyst_summary || '—'}
                  {c.catalyst_vs_industry ? ` · ${c.catalyst_vs_industry}` : ''}
                </div>
                <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 4 }}>
                  <b style={{ color: BB.text2 }}>Relative:</b> {c.relative_performance_summary || '—'}
                </div>
                {c.primary_risk && (
                  <div style={{ fontSize: TYPE.xs, color: BB.red, marginTop: 6 }}>Risk: {c.primary_risk}</div>
                )}

                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginTop: 10, alignItems: 'center' }}>
                  <Link
                    to={`/watch/intelligence/${c.symbol}`}
                    style={{
                      background: BB.bgShift,
                      border: `1px solid ${BB.border}`,
                      color: BB.text0,
                      borderRadius: 8,
                      padding: '6px 9px',
                      fontSize: TYPE.xs,
                      fontWeight: 900,
                      textDecoration: 'none',
                    }}
                    onClick={e => e.stopPropagation()}
                  >
                    OPEN INTELLIGENCE
                  </Link>
                  <span style={{ fontSize: TYPE.xs, color: BB.text3 }}>{c.next_operator_action || '—'}</span>
                </div>
              </div>
            )
          })}
        </div>

        <aside
          style={{
            background: BB.bgPanel,
            border: `1px solid ${BB.border}`,
            borderRadius: 12,
            position: 'sticky',
            top: 12,
            overflow: 'hidden',
          }}
          data-intelligence-inspector
        >
          {sel ? (
            <>
              <div style={{ padding: 14, borderBottom: `1px solid ${BB.border}` }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                  <div>
                    <div style={{ fontSize: TYPE.xl, fontWeight: 950 }}>{sel.symbol}</div>
                    <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 2 }}>
                      {sel.company} · {sel.sector} / {sel.industry}
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: TYPE.md, fontWeight: 900 }}>{money(sel.last)}</div>
                    <div style={{ fontSize: TYPE.xs, color: Number(sel.day_change_pct) >= 0 ? BB.green : BB.red }}>{pct(sel.day_change_pct)}</div>
                  </div>
                </div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
                  <span data-primary-rating style={{ border: `1px solid ${BB.border}`, borderRadius: 999, padding: '4px 8px', fontSize: TYPE.xs, fontWeight: 950, color: BB.green }}>
                    STREET {sel.street_rating}
                  </span>
                  <span style={{ border: `1px solid ${BB.border}`, borderRadius: 999, padding: '4px 8px', fontSize: TYPE.xs, color: stateColor(sel.trade_ai_state) }}>
                    Trade AI: {sel.trade_ai_state}
                  </span>
                </div>
                <div style={{ fontSize: TYPE.md, fontWeight: 800, marginTop: 10, lineHeight: 1.4 }}>{sel.one_line_thesis}</div>
              </div>
              <Section title="What the company does">
                <div style={{ fontSize: TYPE.sm, color: BB.text1, lineHeight: 1.45 }} data-company-summary>
                  {sel.company_summary || 'Company description unavailable — typed data gap.'}
                </div>
              </Section>
              <Section title="What to do now">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                  <Fact k="Operator action" v={sel.next_operator_action || '—'} />
                  <Fact k="Proposal eligible" v={sel.proposal_allowed ? 'YES' : 'NO'} />
                  <Fact k="Primary risk" v={sel.primary_risk || '—'} />
                  <Fact k="Next review" v={sel.next_review_time || '—'} />
                </div>
              </Section>
              <Section title="CIO + Maria (card-visible)">
                <div style={{ display: 'grid', gap: 6 }}>
                  <ReviewBox title="CIO" rev={sel.cio_review} />
                  <ReviewBox title="Maria" rev={sel.maria_review} deep />
                  <ReviewBox title="Sentinel" rev={sel.sentinel_review} />
                </div>
              </Section>
              <Section title="Catalyst vs industry">
                <div style={{ fontSize: TYPE.sm, color: BB.text1 }}>{sel.catalyst_summary || '—'}</div>
                <div style={{ fontSize: TYPE.xs, color: BB.text3, marginTop: 4 }}>{sel.catalyst_vs_industry || '—'}</div>
              </Section>
              <Section title="Relative performance">
                <div style={{ fontSize: TYPE.sm, color: BB.text1 }}>{sel.relative_performance_summary || '—'}</div>
              </Section>
              <Section title="Quote provenance">
                <div style={{ fontSize: TYPE.xs, color: BB.text3, lineHeight: 1.5 }}>
                  {sel.price_as_of || '—'} · {sel.price_source || '—'} · {sel.freshness_state || '—'} · {sel.market_session || '—'}
                  <br />
                  quote_id={sel.quote_id != null ? String(sel.quote_id) : '—'} · {sel.source_record_id || '—'}
                </div>
              </Section>
              <div style={{ padding: 12 }}>
                <Link
                  to={`/watch/intelligence/${sel.symbol}`}
                  style={{
                    display: 'inline-block',
                    background: BB.bgShift,
                    border: `1px solid ${BB.border}`,
                    color: BB.text0,
                    borderRadius: 8,
                    padding: '8px 10px',
                    fontSize: TYPE.xs,
                    fontWeight: 900,
                    textDecoration: 'none',
                  }}
                >
                  OPEN FULL SYMBOL INTELLIGENCE
                </Link>
              </div>
            </>
          ) : (
            <div style={{ padding: 14, color: BB.text3, fontSize: TYPE.sm }}>Select a card</div>
          )}
        </aside>
      </div>
    </div>
  )
}

function Chip({ children, good }: { children: React.ReactNode; good?: boolean }) {
  return (
    <span
      style={{
        border: `1px solid ${BB.border}`,
        background: BB.bgPanel,
        borderRadius: 999,
        padding: '5px 9px',
        fontSize: TYPE.xs,
        color: good ? BB.green : BB.text3,
      }}
    >
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
      <div style={{ fontSize: TYPE.xs, color: BB.text1, marginTop: 3, lineHeight: 1.35 }}>{v}</div>
    </div>
  )
}
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ padding: '12px 14px', borderTop: `1px solid ${BB.border}` }}>
      <div style={{ fontSize: TYPE.xs, color: BB.text3, textTransform: 'uppercase', letterSpacing: 0.8, fontWeight: 900, marginBottom: 8 }}>
        {title}
      </div>
      {children}
    </div>
  )
}
